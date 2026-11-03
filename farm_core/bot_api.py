import json
import logging
from datetime import timedelta
from uuid import UUID

import pyotp
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from farm_core.circle import confirm_opened, finish_entry, stop_run, _active_entry
from farm_core.event_log import log_event
from farm_core.metrics import put_daily_metric
from farm_core.mode_labels import normalize_modes
from farm_core.models import (
    Account,
    AccountLoginSecret,
    AgentCommand,
    AccountSnapshot,
    BotSession,
    FolderRun,
    MarketFilter,
    MarketFilterList,
    NotifyOutbox,
    RunEntry,
    SbcAssignment,
    SbcSet,
    SbcSetItem,
    SbcTemplate,
    SnipeSettingsDoc,
)
from farm_core.sbc import record_attempt
from farm_core.telegram_send import send_auto_buy


class ApiError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def session_start(body):
    email = _email(body.get('email'))
    if not email:
        raise ApiError('bad_request', 'Нужен email')
    account = _find_account(body.get('ea_account_id'), email)
    known = account is not None
    entry = _active_entry(email)
    if entry is not None:
        confirm_opened(email)
        session = BotSession.objects.filter(
            run_entry=entry,
            finished_at__isnull=True,
        ).order_by('-started_at').first()
        if session is None:
            session = _new_session(email, account, entry, body)
        else:
            _touch(session, account, body)
    else:
        session = BotSession.objects.filter(
            email__iexact=email,
            finished_at__isnull=True,
            run_entry__isnull=True,
        ).order_by('-started_at').first()
        if session is None:
            session = _new_session(email, account, None, body)
        else:
            _touch(session, account, body)
    return {
        'session': str(session.id),
        'account': {'id': account.id if account else None, 'known': known},
        'run': _run_payload(entry),
        'steps': _steps(entry),
        'versions': _versions(account),
        'snipe_settings': _snipe_if_newer(account, body.get('snipe_settings_version')),
        'heartbeat_sec': getattr(settings, 'HEARTBEAT_SEC', 60),
    }


def session_bind(body):
    session = _session(body)
    ea_id = _parse_ea_id(body.get('ea_account_id'))
    if ea_id is None:
        raise ApiError('bad_request', 'Нужен ea_account_id')
    email = _email(session.email)
    by_id = _account_by_ea(ea_id)
    by_email = _account_by_email(email)
    if by_id and by_email and by_id.id != by_email.id:
        raise ApiError('conflict', 'EA id уже у другого email')
    if by_id:
        if email and by_id.email and _email(by_id.email).lower() != email.lower():
            raise ApiError('conflict', 'EA id уже у другого email')
        account = by_id
        if email and not account.email:
            account.email = email
        account.name = body.get('account_name') or account.name
        if body.get('coins') is not None:
            account.balance = int(body.get('coins') or 0)
        _mark_linked(account)
        account.save()
    elif by_email:
        if by_email.ea_account_id not in (None, ea_id):
            raise ApiError('conflict', 'У этого email уже другой EA id')
        account = by_email
        account.ea_account_id = ea_id
        account.name = body.get('account_name') or account.name
        if body.get('coins') is not None:
            account.balance = int(body.get('coins') or 0)
        _mark_linked(account)
        account.save()
        logging.info('Записал EA id %s аккаунту %s', ea_id, email)
    else:
        account = Account.objects.create(
            ea_account_id=ea_id,
            name=body.get('account_name') or '',
            email=email or None,
            balance=int(body.get('coins') or 0),
        )
        _mark_linked(account)
        account.save(update_fields=['linked_at'])
        logging.info('Создал аккаунт по EA id %s email %s', ea_id, email)
    session.account = account
    session.save(update_fields=['account', 'last_seen_at'])
    if session.run_entry_id and session.run_entry.account_id is None:
        session.run_entry.account = account
        session.run_entry.save(update_fields=['account'])
    return {'account': {'id': account.id, 'known': True}}


def session_credentials(body):
    session = _session(body)
    if session.run_entry_id is None:
        raise ApiError('not_in_run', 'Учётные данные только для круга')
    if session.credentials_reads >= 3:
        raise ApiError('rate_limited', 'Слишком часто запрашивают вход')
    session.credentials_reads += 1
    account = session.account or _find_account(body.get('ea_account_id'), session.email)
    fields = ['credentials_reads', 'last_seen_at']
    if account is not None and session.account_id is None:
        session.account = account
        fields.append('account')
    session.save(update_fields=fields)
    secret = None
    if account is not None:
        secret = AccountLoginSecret.objects.filter(account=account).first()
    return {
        'email': session.email or (account.email if account is not None else ''),
        'code_ea': _code_ea(secret),
        'ea_password': (secret.ea_password if secret is not None else '') or '',
    }


def session_heartbeat(body):
    session = _session(body)
    _touch(session, session.account, body)
    action = 'continue'
    if session.run_entry_id and session.run_entry.run.state != FolderRun.STATE_ACTIVE:
        action = 'stop'
    return {'action': action}


def session_finish(body):
    session = None
    if body.get('session'):
        try:
            session = BotSession.objects.filter(id=UUID(str(body.get('session')))).first()
        except ValueError:
            session = None
    email = _email(body.get('email'))
    if session is None and email:
        session = BotSession.objects.filter(email__iexact=email).order_by('-started_at').first()
    if session is None and not email:
        raise ApiError('bad_request', 'Нужна сессия или email')
    if session and session.finished_at:
        return {'action': session.finish_action or 'close_browser'}
    reason = body.get('reason') or 'done'
    target_email = (session.email if session else email) or ''
    keep = reason == 'page_not_loaded'
    action = 'keep_open' if keep else 'close_browser'
    log_event(
        'Аккаунт %s закончил сессию: %s, %s'
        % (target_email, reason, 'оставлю открытым' if keep else 'закрою')
    )
    if not keep:
        finish_entry(target_email, reason=reason)
    if session:
        session.finished_at = timezone.now()
        session.finish_reason = reason
        session.finish_action = action
        session.save(update_fields=['finished_at', 'finish_reason', 'finish_action', 'last_seen_at'])
    return {'action': action}


def events_push(body):
    session = _session(body)
    accepted = []
    rejected = []
    for event in body.get('events') or []:
        event_id = str(event.get('id') or '')
        try:
            _apply_event(session, event)
            accepted.append(event_id)
        except ApiError as error:
            rejected.append({'id': event_id, 'code': error.code})
        except Exception:
            logging.info('Событие %s не принято', event_id)
            rejected.append({'id': event_id, 'code': 'bad_request'})
    return {'accepted': accepted, 'rejected': rejected}


def account_snapshot(body):
    session = _session(body)
    if session.account_id is None:
        raise ApiError('bad_request', 'Аккаунт ещё не привязан')
    snap = body.get('snapshot') or {}
    AccountSnapshot.objects.update_or_create(
        account=session.account,
        defaults={
            'coins': snap.get('coins'),
            'packs_count': snap.get('packs_count'),
            'market_limit': snap.get('market_limit'),
            'market_reset_hour': snap.get('market_reset_hour'),
            'market_stamps': snap.get('market_stamps') or [],
            'taken_at': timezone.now(),
        },
    )
    return {}


def sbc_list(body):
    session = _session(body)
    assignment = None
    if session.account_id:
        assignment = SbcAssignment.objects.filter(
            account=session.account,
            state=SbcAssignment.STATE_ACTIVE,
        ).select_related('sbc_set').first()
    items = []
    seen = set()
    if assignment:
        for item in assignment.sbc_set.items.select_related('template').order_by('position'):
            seen.add(item.template.name)
            items.append(_sbc_item(item.template, item.priority))
    common = SbcSet.objects.filter(common=True).first()
    if common:
        for item in common.items.select_related('template').order_by('position'):
            if item.template.name in seen:
                continue
            items.append(_sbc_item(item.template, False))
    payload = {
        'assignment': None,
        'items': items,
    }
    if assignment:
        payload['assignment'] = {
            'id': assignment.id,
            'set_id': assignment.sbc_set_id,
            'name': assignment.sbc_set.name,
            'version': assignment.set_version,
        }
    return payload


def sbc_finish(body):
    session = _session(body)
    assignment_id = body.get('assignment_id')
    query = SbcAssignment.objects.filter(state=SbcAssignment.STATE_ACTIVE)
    if session.account_id:
        query = query.filter(account=session.account)
    if assignment_id:
        query = query.filter(id=assignment_id)
    query.update(state=SbcAssignment.STATE_FINISHED, finished_at=timezone.now())
    return {}


def sbc_sets(_body):
    items = [
        {
            'id': item.id,
            'name': item.name,
            'version': item.version,
            'common': item.common,
        }
        for item in SbcSet.objects.order_by('name')
    ]
    return {'items': items}


def sbc_save(body):
    saved = []
    conflicts = []
    set_id = body.get('set_id')
    sbc_set = SbcSet.objects.filter(id=set_id).first() if set_id else None
    priority = bool(body.get('priority'))
    for item in body.get('items') or []:
        name = item.get('name') or ''
        payload = item.get('payload') or {}
        base = item.get('base_version')
        template = SbcTemplate.objects.filter(name=name).first()
        if template and base is not None and template.version != base:
            conflicts.append(name)
            continue
        template, _created = SbcTemplate.objects.update_or_create(
            name=name,
            defaults={'payload': payload, 'version': (template.version + 1) if template else 1},
        )
        saved.append({'name': name, 'version': template.version})
        if sbc_set:
            SbcSetItem.objects.update_or_create(
                sbc_set=sbc_set,
                template=template,
                defaults={'priority': priority},
            )
            sbc_set.version += 1
            sbc_set.save(update_fields=['version', 'updated_at'])
    return {'saved': saved, 'conflicts': conflicts}


def market_filters(_body):
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    items = [
        {'title': item.title, 'payload': item.payload, 'version': item.version}
        for item in MarketFilter.objects.filter(enabled=True).order_by('position', 'title')
    ]
    return {'version': listing.version, 'items': items}


def market_filters_save(body):
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    saved = []
    conflicts = []
    for item in body.get('items') or []:
        title = item.get('title') or ''
        current = MarketFilter.objects.filter(title=title).first()
        base = item.get('base_version')
        if current and base is not None and current.version != base:
            conflicts.append(title)
            continue
        obj, _created = MarketFilter.objects.update_or_create(
            title=title,
            defaults={
                'payload': item.get('payload') or {},
                'version': (current.version + 1) if current else 1,
            },
        )
        saved.append(title)
        del obj
    listing.version += 1
    listing.save(update_fields=['version', 'updated_at'])
    return {'saved': saved, 'conflicts': conflicts}


def market_filters_remove(body):
    titles = list(body.get('titles') or [])
    MarketFilter.objects.filter(title__in=titles).delete()
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    listing.version += 1
    listing.save(update_fields=['version', 'updated_at'])
    return {'removed': titles}


def snipe_settings_save(body):
    _session(body)
    current = SnipeSettingsDoc.current()
    base = body.get('base_version')
    if current and base is not None and current.version != base:
        raise ApiError('conflict', 'Версия настроек устарела')
    payload = body.get('payload')
    if not isinstance(payload, str):
        payload = json.dumps(payload or {}, ensure_ascii=False)
    doc = SnipeSettingsDoc.write(payload)
    return {'version': doc.version}


def _deliver_auto_buy(outbox, text):
    if outbox.state == NotifyOutbox.STATE_SENT:
        return
    if outbox.text != text or outbox.channel != 'auto_buy':
        outbox.text = text
        outbox.channel = 'auto_buy'
        outbox.save(update_fields=['text', 'channel'])
    if send_auto_buy(text):
        outbox.state = NotifyOutbox.STATE_SENT
        outbox.sent_at = timezone.now()
        outbox.save(update_fields=['state', 'sent_at'])


def notify(body):
    channel = body.get('channel') or 'important'
    text = body.get('text') or ''
    email = _email(body.get('email'))
    if not email and body.get('session'):
        session = _session(body)
        email = session.email
    if email:
        text = '%s %s' % (email, text)
    key = body.get('dedup_key') or ('notify-%s-%s' % (channel, timezone.now().timestamp()))
    outbox, _created = NotifyOutbox.objects.get_or_create(
        dedup_key=str(key)[:80],
        defaults={'channel': channel, 'text': text},
    )
    if channel == 'auto_buy':
        _deliver_auto_buy(outbox, text)
    return {'queued': True}


def solver_solve(body):
    del body
    raise ApiError('upstream_failed', 'Солвер не ответил')


def solver_solutions(body):
    del body
    raise ApiError('upstream_failed', 'Солвер не ответил')


def mark_stalled(now=None):
    now = now or timezone.now()
    minutes = getattr(settings, 'STALL_MINUTES', 5)
    threshold = now - timedelta(minutes=minutes)
    entries = list(
        RunEntry.objects.filter(
            run__state=FolderRun.STATE_ACTIVE,
            state__in=[RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED],
        ).select_related('run', 'run__folder', 'last_command')
    )
    by_run = {}
    for entry in entries:
        seen = entry.last_seen_at or entry.queued_at or entry.run.started_at
        if seen is None or seen >= threshold:
            continue
        by_run.setdefault(entry.run_id, []).append(entry)
    reports = []
    for group in by_run.values():
        run = group[0].run
        stop_run(run)
        for entry in group:
            reason = _stall_reason(entry, minutes)
            log_event(
                'Папка %s зависла, аккаунт %s, %s, круг закрыт'
                % (run.folder.name, entry.email, reason)
            )
            NotifyOutbox.objects.get_or_create(
                dedup_key='stall-%s' % entry.id,
                defaults={
                    'channel': 'important',
                    'text': 'Зависла запись %s (%s)' % (entry.email, reason),
                },
            )
            reports.append(entry.email)
    return reports


def _stall_reason(entry, minutes):
    command = entry.last_command
    waiting = (
        AgentCommand.STATE_PENDING,
        AgentCommand.STATE_ACKED,
    )
    if command is not None and command.state in waiting and command.finished_at is None:
        return 'команда открытия без итога %s мин' % minutes
    return 'нет сигнала %s мин' % minutes


def _new_session(email, account, entry, body):
    client = body.get('client') or {}
    return BotSession.objects.create(
        email=email,
        account=account,
        run_entry=entry,
        client_engine=client.get('engine') or '',
        client_version=client.get('version') or '',
        known_modes=list(client.get('known_modes') or []),
    )


def _touch(session, account, body):
    session.last_seen_at = timezone.now()
    fields = ['last_seen_at']
    if account and session.account_id != account.id:
        session.account = account
        fields.append('account')
    client = body.get('client') or {}
    if client.get('known_modes'):
        session.known_modes = list(client.get('known_modes') or [])
        fields.append('known_modes')
    session.save(update_fields=fields)
    if session.run_entry_id:
        session.run_entry.last_seen_at = timezone.now()
        session.run_entry.save(update_fields=['last_seen_at'])


def _session(body):
    raw = body.get('session')
    if not raw:
        raise ApiError('unknown_session', 'Сессии нет или она закрыта')
    try:
        session_id = UUID(str(raw))
    except ValueError as error:
        raise ApiError('unknown_session', 'Сессии нет или она закрыта') from error
    session = BotSession.objects.filter(id=session_id).select_related(
        'account', 'run_entry', 'run_entry__run', 'run_entry__run__folder'
    ).first()
    if session is None or session.finished_at:
        raise ApiError('unknown_session', 'Сессии нет или она закрыта')
    session.last_seen_at = timezone.now()
    session.save(update_fields=['last_seen_at'])
    if session.run_entry_id:
        session.run_entry.last_seen_at = timezone.now()
        session.run_entry.save(update_fields=['last_seen_at'])
    return session


def _mark_linked(account):
    if account.linked_at is None:
        account.linked_at = timezone.now()


def _apply_market_open(account, opened):
    account.market_open = opened
    if opened:
        account.market_seen_open = True
        return
    if account.market_seen_open:
        account.ban = True
        logging.info('Бан %s: рынок был открыт и закрылся', account.email)


def _email(value):
    return (value or '').strip()


def _parse_ea_id(ea_id):
    if ea_id in (None, ''):
        return None
    try:
        return int(ea_id)
    except (TypeError, ValueError):
        return None


def _account_by_ea(ea_id):
    parsed = _parse_ea_id(ea_id)
    if parsed is None:
        return None
    return Account.objects.filter(ea_account_id=parsed).first()


def _account_by_email(email):
    cleaned = _email(email)
    if not cleaned:
        return None
    return Account.objects.filter(email__iexact=cleaned).first()


def _find_account(ea_id, email):
    return _account_by_ea(ea_id) or _account_by_email(email)


def _run_payload(entry):
    if entry is None:
        return None
    return {
        'entry_id': entry.id,
        'folder': entry.run.folder.name,
        'play_mode': entry.run.play_mode,
    }


def _steps(entry):
    if entry is None:
        return []
    steps = []
    for item in normalize_modes(entry.run.modes):
        steps.append({'key': item.get('key'), 'value': item.get('value')})
    return steps


def _versions(account):
    listing = MarketFilterList.objects.order_by('id').first()
    snipe = SnipeSettingsDoc.current()
    assignment = None
    if account:
        assignment = SbcAssignment.objects.filter(
            account=account, state=SbcAssignment.STATE_ACTIVE
        ).first()
    return {
        'sbc': assignment.set_version if assignment else 0,
        'market_filters': listing.version if listing else 0,
        'snipe_settings': snipe.version if snipe else 0,
    }


def _snipe_if_newer(account, client_version):
    del account
    doc = SnipeSettingsDoc.current()
    if doc is None:
        return None
    try:
        current = int(client_version or 0)
    except (TypeError, ValueError):
        current = 0
    if doc.version <= current:
        return None
    return {'payload': doc.payload, 'version': doc.version}


def _code_ea(secret):
    if secret is None:
        return ''
    seed = (secret.totp_seed or '').strip()
    if not seed:
        return ''
    try:
        return pyotp.TOTP(seed).now()
    except Exception:
        logging.info('Не удалось посчитать код входа по TOTP')
        return ''


def _sbc_item(template, priority):
    return {
        'name': template.name,
        'priority': priority,
        'payload': template.payload,
        'version': template.version,
    }


def _apply_event(session, event):
    kind = event.get('type')
    data = event.get('data') or {}
    account = session.account
    if kind == 'metric.day':
        if account is None:
            raise ApiError('bad_request', 'Нет аккаунта')
        day = parse_date(str(data.get('date') or ''))
        put_daily_metric(account, day, data.get('name') or '', int(data.get('value') or 0))
        return
    if kind == 'sbc.attempt':
        if account is None:
            raise ApiError('bad_request', 'Нет аккаунта')
        occurred = parse_datetime(str(event.get('at') or '')) or timezone.now()
        record_attempt(
            account,
            str(event.get('id')),
            data.get('name') or data.get('sbc_name') or '',
            data.get('outcome') or 'failed',
            occurred,
            priority=bool(data.get('priority')),
            reason=data.get('reason') or '',
            challenge_id=str(data.get('challenge_id') or ''),
        )
        return
    if kind == 'account.flag':
        if account is None:
            raise ApiError('bad_request', 'Нет аккаунта')
        if 'ban' in data:
            account.ban = bool(data.get('ban'))
        if 'fix_player' in data:
            account.fix_player_at = str(data.get('fix_player') or '')
        if data.get('preview_pack_opened_at'):
            parsed = parse_datetime(str(data.get('preview_pack_opened_at')))
            account.preview_pack_opened_at = parsed
        if 'market_open' in data:
            _apply_market_open(account, bool(data.get('market_open')))
        account.save()
        return
