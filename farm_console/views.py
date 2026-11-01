import json
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from farm_core.agent_queue import enqueue_open, enqueue_stop_chrome
from farm_core.circle import continue_folder, start_folder, stop_run
from farm_core.folder_filter import (
    FILTER_FIELDS,
    FILTER_OPS,
    default_filter,
    evaluate_folder,
    filter_template,
)
from farm_core.csv_import import import_csv
from farm_core.legacy_import import import_legacy
from farm_core.mode_labels import parse_modes_text
from farm_core.models import (
    Account,
    AgentCommand,
    DailyMetric,
    Folder,
    FolderManual,
    FolderRun,
    ImportReport,
    MarketFilter,
    MarketFilterList,
    NotifyOutbox,
    RunEntry,
    SbcAssignment,
    SbcAttempt,
    SbcSet,
    SbcSetItem,
    Schedule,
    ScheduleFire,
    SnipeSettingsDoc,
    Worker,
)
from farm_core.sbc import clear_assignment, clear_set_assignments
from farm_core.workers import ensure_configured_worker
from farm_site.settings import LOCAL_SETTINGS_PATH, load_local_settings


def login_view(request):
    error = ''
    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username') or '',
            password=request.POST.get('password') or '',
        )
        if user is not None:
            login(request, user)
            return redirect('farm-home')
        error = 'Неверный логин или пароль'
    return render(request, 'farm_console/login.html', {'error': error})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('farm-login')


@login_required
@require_http_methods(['GET', 'POST'])
def farm_home(request):
    ensure_configured_worker()
    message = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'stall':
            try:
                minutes = int(request.POST.get('stall_minutes') or 5)
            except ValueError:
                minutes = 5
            if minutes < 1:
                minutes = 1
            _save_stall_flags(
                minutes,
                request.POST.get('stall_kill_chrome') == '1',
                request.POST.get('page_not_loaded_close') == '1',
            )
            message = 'Порог зависания сохранён'
        elif action in ('start', 'continue', 'stop'):
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            message = _run_action(folder, action, request.user.username)
        elif action == 'stop_chrome':
            worker = Worker.objects.filter(enabled=True).order_by('id').first()
            if worker:
                enqueue_stop_chrome(worker)
                message = 'Команда stop_chrome поставлена'
    folders = [_folder_row(folder) for folder in Folder.objects.all().order_by('name')]
    worker = Worker.objects.order_by('id').first()
    return render(request, 'farm_console/farm.html', {
        'folders': folders,
        'message': message,
        'worker': worker,
        'worker_alive': _worker_alive(worker),
        'heartbeat_sec': getattr(settings, 'HEARTBEAT_SEC', 60),
        'stall_minutes': getattr(settings, 'STALL_MINUTES', 5),
        'stall_kill_chrome': getattr(settings, 'STALL_KILL_CHROME', False),
        'page_not_loaded_close': getattr(settings, 'PAGE_NOT_LOADED_CLOSE', False),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def folder_page(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    message = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'save':
            folder.name = request.POST.get('name') or folder.name
            folder.play_mode = request.POST.get('play_mode') or 'SBCmode'
            folder.open_at_a_time = int(request.POST.get('open_at_a_time') or 1)
            folder.refresh_on_start = request.POST.get('refresh_on_start') == '1'
            folder.kill_chrome_before_scheduled = request.POST.get('kill_chrome_before_scheduled') == '1'
            folder.order = request.POST.get('order') or 'email'
            folder.modes_text = request.POST.get('modes_text') or ''
            folder.modes = [
                {'key': item['key'], 'value': item['value']}
                for item in parse_modes_text(folder.modes_text)
            ]
            folder.filter = _read_filter(request)
            set_id = request.POST.get('sbc_set_id') or ''
            folder.sbc_set = SbcSet.objects.filter(id=set_id).first() if set_id else None
            folder.save()
            message = 'Папка сохранена'
        elif action == 'template':
            applied = filter_template(
                request.POST.get('template') or '',
                request.POST.get('template_extra') or '',
            )
            if applied is None:
                message = 'Шаблон не применён: нужно имя СБЧ или число'
            else:
                folder.filter = applied
                folder.save(update_fields=['filter'])
                message = 'Шаблон фильтра записан'
        elif action in ('start', 'continue', 'stop'):
            message = _run_action(folder, action, request.user.username)
        elif action == 'include':
            account = Account.objects.filter(id=request.POST.get('account_id')).first()
            if account:
                FolderManual.objects.update_or_create(
                    folder=folder,
                    account=account,
                    defaults={'kind': FolderManual.KIND_INCLUDE},
                )
                message = 'Добавлен вручную'
        elif action == 'exclude':
            account = Account.objects.filter(id=request.POST.get('account_id')).first()
            if account:
                FolderManual.objects.update_or_create(
                    folder=folder,
                    account=account,
                    defaults={'kind': FolderManual.KIND_EXCLUDE},
                )
                message = 'Исключён вручную'
        elif action == 'clear_manual':
            FolderManual.objects.filter(
                folder=folder,
                id=request.POST.get('manual_id'),
            ).delete()
            message = 'Ручная пометка снята'
    selected, missing = evaluate_folder(folder)
    run = folder.runs.filter(state=FolderRun.STATE_ACTIVE).first()
    entries = list(run.entries.select_related('account', 'last_command').order_by('position')) if run else []
    manuals = list(folder.manuals.select_related('account').order_by('kind', 'account__email'))
    recent_runs = list(folder.runs.order_by('-started_at')[:10])
    return render(request, 'farm_console/folder.html', {
        'folder': folder,
        'accounts': selected,
        'missing': missing,
        'run': run,
        'entries': entries,
        'sets': SbcSet.objects.all(),
        'all_accounts': Account.objects.order_by('email'),
        'manuals': manuals,
        'recent_runs': recent_runs,
        'message': message,
        'parsed_modes': parse_modes_text(folder.modes_text),
        'filter_fields': FILTER_FIELDS,
        'filter_ops': FILTER_OPS,
        'filter_rows': folder.filter or [],
    })


@login_required
@require_http_methods(['GET', 'POST'])
def folder_create(request):
    if request.method == 'POST':
        folder = Folder.objects.create(
            name=request.POST.get('name') or 'Папка',
            filter=default_filter(),
            refresh_on_start=True,
        )
        return redirect('farm-folder', folder_id=folder.id)
    return render(request, 'farm_console/folder_create.html')


@login_required
def schedule_page(request):
    message = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            Schedule.objects.create(
                name=request.POST.get('name') or folder.name,
                folder=folder,
                action=request.POST.get('schedule_action') or Schedule.ACTION_START,
                days=_read_days(request),
                start_time=request.POST.get('start_time') or '00:00',
                stop_time=request.POST.get('stop_time') or '23:59',
                enabled=request.POST.get('enabled') == '1',
                kill_chrome_before=request.POST.get('kill_chrome_before') == '1',
            )
            message = 'Расписание создано'
        elif action == 'toggle':
            schedule = get_object_or_404(Schedule, id=request.POST.get('schedule_id'))
            schedule.enabled = not schedule.enabled
            schedule.save(update_fields=['enabled'])
        elif action == 'run_now':
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            result = start_folder(folder, started_by=request.user.username)
            message = _result_text(result)
    schedules = list(Schedule.objects.select_related('folder').all())
    last_fires = {}
    for fire in ScheduleFire.objects.select_related('schedule').order_by('-fired_at')[:200]:
        last_fires.setdefault(fire.schedule_id, fire)
    rows = []
    for item in schedules:
        rows.append({'schedule': item, 'last_fire': last_fires.get(item.id)})
    return render(request, 'farm_console/schedule.html', {
        'rows': rows,
        'folders': Folder.objects.order_by('name'),
        'message': message,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def pc_page(request):
    ensure_configured_worker()
    message = ''
    worker = Worker.objects.filter(enabled=True).order_by('id').first()
    if request.method == 'POST' and worker:
        action = request.POST.get('action')
        if action == 'open':
            email = (request.POST.get('email') or '').strip()
            if email:
                enqueue_open(worker, email)
                message = 'Команда open поставлена: %s' % email
        elif action == 'stop_chrome':
            enqueue_stop_chrome(worker)
            message = 'Команда stop_chrome поставлена'
        elif action == 'disable':
            worker.enabled = False
            worker.save(update_fields=['enabled'])
            message = 'ПК выключен'
        elif action == 'enable':
            worker.enabled = True
            worker.save(update_fields=['enabled'])
            message = 'ПК включён'
    commands = []
    if worker:
        commands = list(worker.commands.order_by('-created_at')[:50])
    stale = [
        command
        for command in commands
        if command.state == AgentCommand.STATE_ACKED
        and command.acked_at
        and (timezone.now() - command.acked_at).total_seconds() > 120
    ]
    return render(request, 'farm_console/pc.html', {
        'workers': Worker.objects.all(),
        'commands': commands,
        'stale': stale,
        'message': message,
        'worker_alive': _worker_alive(worker),
    })


@login_required
def accounts_page(request):
    query = (request.GET.get('q') or '').strip()
    accounts = Account.objects.all()
    if query:
        found = Account.objects.filter(email__icontains=query) | Account.objects.filter(
            name__icontains=query
        )
        if query.isdigit():
            found = found | Account.objects.filter(ea_account_id=int(query))
        accounts = found.distinct()
    accounts = accounts.order_by('-balance', 'email')
    return render(request, 'farm_console/accounts.html', {
        'accounts': accounts[:300],
        'query': query,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def account_page(request, account_id):
    account = get_object_or_404(Account, id=account_id)
    message = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'unassign':
            cleared = clear_assignment(account)
            message = 'Набор СБЧ снят' if cleared else 'Активного набора нет'
        elif action == 'save_snipe':
            payload = request.POST.get('snipe_payload') or ''
            SnipeSettingsDoc.write(payload, updated_by=request.user.username)
            message = 'Настройки снайпа записаны для всех аккаунтов'
    assignment = SbcAssignment.objects.filter(
        account=account,
        state=SbcAssignment.STATE_ACTIVE,
    ).select_related('sbc_set').first()
    today = timezone.localdate()
    days = [today - timedelta(days=offset) for offset in range(7)]
    week_rows = [_account_day(account, day) for day in days]
    snipe = SnipeSettingsDoc.current()
    last_run = (
        RunEntry.objects.filter(account=account)
        .select_related('run', 'run__folder')
        .order_by('-id')
        .first()
    )
    return render(request, 'farm_console/account.html', {
        'account': account,
        'assignment': assignment,
        'week_rows': week_rows,
        'today': today,
        'message': message,
        'snipe': snipe,
        'last_run': last_run,
        'account_count': Account.objects.count(),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def import_page(request):
    message = ''
    report = ImportReport.objects.order_by('-created_at').first()
    if request.method == 'POST':
        uploaded = request.FILES.get('csv_file')
        path = (request.POST.get('path') or '').strip()
        imported = None
        if uploaded:
            imported = import_csv(uploaded=uploaded)
        elif path:
            imported = import_legacy(path)
        if imported is not None:
            report = imported
            if report.unresolved:
                message = 'Импорт завершён, есть спорные строки: %s' % len(report.unresolved)
            else:
                message = 'Импорт завершён без спорных строк'
        elif request.POST.get('import_kind') == 'csv':
            message = 'Выберите файл CSV'
    return render(request, 'farm_console/import.html', {
        'report': report,
        'message': message,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def filters_page(request):
    message = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'attach_set':
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            sbc_set = get_object_or_404(SbcSet, id=request.POST.get('sbc_set_id'))
            folder.sbc_set = sbc_set
            folder.save(update_fields=['sbc_set'])
            message = 'Набор «%s» привязан к папке «%s»' % (sbc_set.name, folder.name)
        elif action == 'clear_set':
            sbc_set = get_object_or_404(SbcSet, id=request.POST.get('sbc_set_id'))
            count = clear_set_assignments(sbc_set)
            message = 'Снято назначений: %s' % count
        elif action == 'replace_market':
            message = _replace_market(request.POST.get('market_json') or '')
        elif action == 'save_snipe':
            payload = request.POST.get('snipe_payload') or ''
            SnipeSettingsDoc.write(payload, updated_by=request.user.username)
            message = 'Настройки снайпа сохранены'
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    market_items = list(MarketFilter.objects.order_by('position', 'title'))
    sets = []
    for sbc_set in SbcSet.objects.order_by('name'):
        sets.append({
            'set': sbc_set,
            'items': sbc_set.items.count(),
            'assigned': SbcAssignment.objects.filter(
                sbc_set=sbc_set,
                state=SbcAssignment.STATE_ACTIVE,
            ).count(),
            'folders': list(Folder.objects.filter(sbc_set=sbc_set)),
        })
    return render(request, 'farm_console/filters.html', {
        'sets': sets,
        'folders': Folder.objects.order_by('name'),
        'market_items': market_items,
        'market_version': listing.version,
        'market_json': json.dumps(
            [{'title': item.title, 'payload': item.payload} for item in market_items],
            ensure_ascii=False,
            indent=2,
        ),
        'snipe': SnipeSettingsDoc.current(),
        'message': message,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def sbc_week_page(request):
    message = ''
    week = timezone.now() - timedelta(days=7)
    if request.method == 'POST':
        action = request.POST.get('action')
        extra = request.POST.get('extra') or ''
        applied = filter_template(action, extra)
        if applied is None:
            message = 'Не вышло создать папку: нужно имя СБЧ или число'
        else:
            name = request.POST.get('name') or _sbc_folder_name(action, extra)
            folder = Folder.objects.create(
                name=name,
                filter=applied,
                refresh_on_start=True,
            )
            return redirect('farm-folder', folder_id=folder.id)
    names = (
        SbcAttempt.objects.filter(occurred_at__gte=week)
        .values('sbc_name', 'priority')
        .annotate(
            collected=Count('id', filter=Q(outcome=SbcAttempt.OUTCOME_COLLECTED)),
            failed=Count('id', filter=Q(outcome=SbcAttempt.OUTCOME_FAILED)),
            accounts=Count('account', distinct=True),
        )
        .order_by('-priority', 'sbc_name')
    )
    return render(request, 'farm_console/sbc_week.html', {
        'names': names,
        'message': message,
        'has_data': SbcAttempt.objects.filter(occurred_at__gte=week).exists(),
    })


@login_required
def errors_page(request):
    now = timezone.now()
    week = now - timedelta(days=7)
    day = now - timedelta(hours=24)
    workers = list(Worker.objects.all())
    return render(request, 'farm_console/errors.html', {
        'agent_fails': list(
            AgentCommand.objects.filter(
                state=AgentCommand.STATE_FAILED,
                created_at__gte=week,
            ).select_related('worker', 'run', 'run__folder').order_by('-created_at')[:100]
        ),
        'stale_workers': [worker for worker in workers if not _worker_alive(worker)],
        'schedule_errors': list(
            ScheduleFire.objects.filter(fired_at__gte=week)
            .exclude(result='ok')
            .select_related('schedule', 'schedule__folder')
            .order_by('-fired_at')[:100]
        ),
        'notify_stuck': list(
            NotifyOutbox.objects.filter(
                created_at__gte=week,
            ).exclude(state=NotifyOutbox.STATE_SENT).order_by('-created_at')[:100]
        ),
        'open_fails_day': AgentCommand.objects.filter(
            state=AgentCommand.STATE_FAILED,
            created_at__gte=day,
        ).count(),
    })


def _run_action(folder, action, username):
    if action == 'start':
        return _result_text(start_folder(folder, started_by=username))
    if action == 'continue':
        return _result_text(continue_folder(folder, started_by=username))
    run = folder.runs.filter(state=FolderRun.STATE_ACTIVE).first()
    if run:
        stop_run(run)
        return 'Круг остановлен'
    return 'Нет активного круга'


def _folder_row(folder):
    selected, missing = evaluate_folder(folder)
    run = folder.runs.filter(state=FolderRun.STATE_ACTIVE).first()
    progress = _progress(run) if run else None
    now = timezone.now()
    day = now - timedelta(hours=24)
    fails = AgentCommand.objects.filter(
        state=AgentCommand.STATE_FAILED,
        created_at__gte=day,
        run__folder=folder,
    )
    last_fail = fails.order_by('-created_at').first()
    opening = []
    if run:
        opening = list(
            run.entries.filter(
                state__in=[RunEntry.STATE_QUEUED, RunEntry.STATE_OPENED],
            ).select_related('last_command').order_by('position')
        )
    schedule = folder.schedules.filter(enabled=True).order_by('start_time').first()
    return {
        'folder': folder,
        'count': len(selected),
        'missing': missing,
        'run': run,
        'progress': progress,
        'opening': opening,
        'fail_count': fails.count(),
        'last_fail': last_fail.error_text if last_fail else '',
        'schedule': schedule,
        'unknown_modes': [
            item['key'] for item in parse_modes_text(folder.modes_text) if item.get('unknown')
        ],
    }


def _account_day(account, day):
    metrics = {
        item.name: item.value
        for item in DailyMetric.objects.filter(account=account, date=day)
    }
    attempts = list(SbcAttempt.objects.filter(account=account, occurred_at__date=day))
    collected = [item.sbc_name for item in attempts if item.outcome == SbcAttempt.OUTCOME_COLLECTED]
    failed = [item.sbc_name for item in attempts if item.outcome == SbcAttempt.OUTCOME_FAILED]
    opened = (
        RunEntry.objects.filter(account=account, closed_at__date=day)
        .select_related('run', 'run__folder')
        .first()
    )
    return {
        'date': day,
        'market': metrics.get('market_searches'),
        'packs': metrics.get('packs'),
        'preview': metrics.get('preview_packs'),
        'bronze': metrics.get('bronze_store_packs'),
        'collected': collected,
        'failed': failed,
        'opened': opened,
    }


def _worker_alive(worker):
    if worker is None or not worker.last_poll_at:
        return False
    interval = getattr(settings, 'AGENT_POLL_SEC', 4) * 3
    return (timezone.now() - worker.last_poll_at).total_seconds() <= interval


def _replace_market(raw):
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return 'JSON фильтров рынка не разобрался'
    if not isinstance(parsed, list):
        return 'Нужен список фильтров'
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    MarketFilter.objects.all().delete()
    for index, item in enumerate(parsed):
        if not isinstance(item, dict) or not item.get('title'):
            continue
        MarketFilter.objects.create(
            title=item.get('title'),
            payload=item.get('payload') or {},
            position=index,
            version=1,
        )
    listing.version += 1
    listing.save(update_fields=['version', 'updated_at'])
    return 'Список рынка заменён, версия %s' % listing.version


def _sbc_folder_name(action, extra):
    if action == 'priority':
        return 'Не собрали приоритет'
    if action == 'sbc_name':
        return 'Не собрали %s' % extra
    if action == 'nonpriority':
        return 'Неприоритет меньше %s' % (extra or '3')
    return 'Папка СБЧ'


def _save_stall_flags(minutes, kill_chrome, page_close):
    data = load_local_settings(LOCAL_SETTINGS_PATH)
    data['stall_minutes'] = minutes
    data['stall_kill_chrome'] = kill_chrome
    data['page_not_loaded_close'] = page_close
    LOCAL_SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    settings.STALL_MINUTES = minutes
    settings.STALL_KILL_CHROME = kill_chrome
    settings.PAGE_NOT_LOADED_CLOSE = page_close


def _progress(run):
    entries = list(run.entries.all())
    counts = {
        'waiting': 0,
        'queued': 0,
        'opened': 0,
        'closed': 0,
        'failed': 0,
    }
    for entry in entries:
        if entry.state in counts:
            counts[entry.state] += 1
    return counts


def _result_text(result):
    if result.get('ok'):
        data = result.get('data') or {}
        skipped = data.get('skipped') or []
        text = 'Круг %s, команд %s, всего %s' % (
            data.get('run_id'),
            data.get('queued'),
            data.get('total'),
        )
        if skipped:
            text += '; пропущены (другой круг): %s' % ', '.join(skipped)
        return text
    error = result.get('error') or {}
    return error.get('message') or 'Отказ'


def _read_filter(request):
    fields = request.POST.getlist('filter_field')
    ops = request.POST.getlist('filter_op')
    values = request.POST.getlist('filter_value')
    conditions = []
    for field, op, value in zip(fields, ops, values):
        if not field:
            continue
        parsed = value
        if value in ('true', 'True'):
            parsed = True
        elif value in ('false', 'False'):
            parsed = False
        elif value.isdigit() or (value.startswith('-') and value[1:].isdigit()):
            parsed = int(value)
        conditions.append({'field': field, 'op': op, 'value': parsed})
    return conditions


def _read_days(request):
    days = []
    for item in request.POST.getlist('days'):
        if item.isdigit():
            days.append(int(item))
    return days
