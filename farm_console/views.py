import json
import logging
from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from farm_core.agent_queue import enqueue_close, enqueue_open, enqueue_stop_chrome
from farm_core.catalog_forms import (
    market_row_view,
    remove_market_row,
    save_market_row,
    save_sbc_tile,
    save_snipe_form,
    selected_sbc,
    snipe_form_values,
)
from farm_core.circle import continue_folder, start_folder, stop_run, sync_active_run
from farm_core.folder_filter import (
    ACCOUNT_FILTER_PRESETS,
    FILTER_PRESETS,
    OPEN_RULES,
    accounts_for_start,
    add_members,
    conditions_from_keys,
    default_filter,
    filter_template,
    folder_accounts,
    search_accounts,
)
from farm_core.csv_import import import_csv
from farm_core.legacy_import import import_legacy
from farm_core.mode_catalog import (
    default_folder_modes,
    editor_state,
    modes_from_post,
    modes_preview,
    modes_to_text,
)
from farm_core.mode_labels import parse_modes_text
from farm_core.models import (
    Account,
    AgentCommand,
    DailyMetric,
    Folder,
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
from farm_core.sbc import attach_week_sbc, clear_assignment, clear_set_assignments
from farm_core.workers import ensure_configured_worker
from farm_site.settings import LOCAL_SETTINGS_PATH, load_local_settings

logger = logging.getLogger(__name__)


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
            minutes = _positive_minutes(request.POST.get('stall_minutes'), 5)
            silent = _positive_minutes(request.POST.get('silent_minutes'), 2)
            _save_stall_minutes(minutes, silent)
            message = 'Порог зависания сохранён'
        elif action in ('start', 'continue', 'stop'):
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            message = _run_action(folder, action, request.user.username)
        elif action == 'stop_chrome':
            worker = Worker.objects.filter(enabled=True).order_by('id').first()
            if worker:
                enqueue_stop_chrome(worker)
                message = 'Команда stop_chrome поставлена'
    active_folders = Folder.objects.filter(
        runs__state=FolderRun.STATE_ACTIVE,
    ).distinct().order_by('name')
    folders = [_folder_row(folder) for folder in active_folders]
    worker = Worker.objects.order_by('id').first()
    return render(request, 'farm_console/farm.html', {
        'folders': folders,
        'message': message,
        'worker': worker,
        'worker_alive': _worker_alive(worker),
        'heartbeat_sec': getattr(settings, 'HEARTBEAT_SEC', 60),
        'stall_minutes': getattr(settings, 'STALL_MINUTES', 5),
        'silent_minutes': max(1, int(getattr(settings, 'OPEN_GRACE_SEC', 120) or 120) // 60),
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
            folder.open_at_a_time = int(request.POST.get('open_at_a_time') or 1)
            folder.order = request.POST.get('order') or 'email'
            folder.save()
            sync_active_run(folder)
            message = 'Папка сохранена'
        elif action in ('start', 'continue', 'stop'):
            message = _run_action(folder, action, request.user.username)
        elif action == 'add_selected':
            ids = request.POST.getlist('account_id')
            picked = list(Account.objects.filter(id__in=ids).order_by('email', 'id'))
            _members, added = add_members(folder, picked)
            logger.info(
                'В папку %s добавлено %s: %s',
                folder.name,
                added,
                [account.email for account in picked],
            )
            message = 'В папку добавлено: %s' % added
        elif action == 'remove_member':
            folder.members.filter(account_id=request.POST.get('account_id')).delete()
            message = 'Аккаунт снят с папки'
        elif action == 'clear_members':
            count = folder.members.count()
            folder.members.all().delete()
            logger.info('Состав папки %s очищен: снято %s', folder.name, count)
            message = 'Снято с папки: %s' % count
        elif action == 'delete':
            run = folder.runs.filter(state=FolderRun.STATE_ACTIVE).first()
            if run:
                stop_run(run)
            name = folder.name
            folder.delete()
            logger.info('Папка %s удалена', name)
            messages.success(request, 'Папка удалена')
            return redirect('farm-folder-create')
    members = folder_accounts(folder)
    ready, missing_ready = accounts_for_start(folder)
    found, missing, searched = _load_found(request, folder.id)
    run = folder.runs.filter(state=FolderRun.STATE_ACTIVE).first()
    entries = list(run.entries.select_related('account', 'last_command').order_by('position')) if run else []
    recent_runs = list(folder.runs.order_by('-started_at')[:10])
    return render(request, 'farm_console/folder.html', {
        'folder': folder,
        'members': members,
        'ready': ready,
        'found': found,
        'missing': missing,
        'missing_ready': missing_ready,
        'run': run,
        'entries': entries,
        'recent_runs': recent_runs,
        'message': message,
        'modes_preview': modes_preview(folder.modes),
        'filter_presets': FILTER_PRESETS,
        'searched': searched,
    })


@login_required
@require_POST
def folder_search(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    email_query = (request.POST.get('email') or '').strip()
    keys = request.POST.getlist('filter_key')
    if email_query:
        conditions = conditions_from_keys(['email'], {'email': email_query})
        source = 'email'
    elif keys:
        extras = {}
        fallback = (request.POST.get('filter_extra') or '').strip()
        for key in keys:
            extras[key] = (request.POST.get('extra_%s' % key) or fallback).strip()
        conditions = conditions_from_keys(keys, extras)
        source = 'filter'
    else:
        return HttpResponse(status=204)
    if not conditions:
        return HttpResponse(status=204)
    found, missing = search_accounts(conditions)
    _store_found(request, folder.id, found, missing)
    logger.info(
        'Поиск папки %s: %s %s, найдено %s',
        folder.name,
        source,
        email_query or keys,
        len(found),
    )
    return render(request, 'farm_console/folder_found.html', {
        'folder': folder,
        'found': found,
        'missing': missing,
        'searched': True,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def folder_modes_page(request, folder_id):
    folder = get_object_or_404(Folder, id=folder_id)
    if request.method == 'POST':
        folder.modes = modes_from_post(request.POST)
        folder.modes_text = modes_to_text(folder.modes)
        folder.save(update_fields=['modes', 'modes_text'])
        sync_active_run(folder)
        logger.info(
            'Моды папки %s записаны: %s',
            folder.name,
            [item['key'] for item in folder.modes],
        )
        return redirect('farm-folder', folder_id=folder.id)
    return render(request, 'farm_console/folder_modes.html', {
        'folder': folder,
        'editor': editor_state(folder.modes),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def folder_create(request):
    if request.method == 'POST':
        modes = default_folder_modes()
        folder = Folder.objects.create(
            name=request.POST.get('name') or 'Папка',
            filter=default_filter(),
            refresh_on_start=True,
            modes=modes,
            modes_text=modes_to_text(modes),
        )
        return redirect('farm-folder', folder_id=folder.id)
    folders = Folder.objects.annotate(account_count=Count('members')).order_by('name')
    return render(request, 'farm_console/folder_create.html', {'folders': folders})


@login_required
def schedule_page(request):
    message = ''
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            open_rule, assign_sbc = _read_open(request)
            Schedule.objects.create(
                name=request.POST.get('name') or folder.name,
                folder=folder,
                action=request.POST.get('schedule_action') or Schedule.ACTION_START,
                days=_read_days(request),
                start_time=_parse_clock(request.POST.get('start_time'), time(9, 0)),
                stop_time=_parse_clock(request.POST.get('stop_time'), time(23, 0)),
                enabled=request.POST.get('enabled') == '1',
                kill_chrome_before=True,
                open_rule=open_rule,
                assign_sbc=assign_sbc,
            )
            message = 'Расписание создано'
        elif action == 'save':
            schedule = get_object_or_404(Schedule, id=request.POST.get('schedule_id'))
            folder = get_object_or_404(Folder, id=request.POST.get('folder_id'))
            schedule.name = request.POST.get('name') or folder.name
            schedule.folder = folder
            schedule.action = request.POST.get('schedule_action') or Schedule.ACTION_START
            schedule.days = _read_days(request)
            schedule.start_time = _parse_clock(request.POST.get('start_time'), schedule.start_time)
            schedule.stop_time = _parse_clock(request.POST.get('stop_time'), schedule.stop_time)
            schedule.enabled = request.POST.get('enabled') == '1'
            schedule.open_rule, schedule.assign_sbc = _read_open(request)
            schedule.save()
            logger.info('Расписание %s сохранено', schedule.name)
            message = 'Расписание сохранено'
        elif action == 'toggle':
            schedule = get_object_or_404(Schedule, id=request.POST.get('schedule_id'))
            schedule.enabled = not schedule.enabled
            schedule.save(update_fields=['enabled'])
        elif action == 'delete':
            schedule = get_object_or_404(Schedule, id=request.POST.get('schedule_id'))
            name = schedule.name
            schedule.delete()
            logger.info('Расписание %s удалено', name)
            message = 'Расписание удалено'
        elif action == 'run_now':
            schedule = get_object_or_404(Schedule, id=request.POST.get('schedule_id'))
            result = start_folder(
                schedule.folder,
                started_by=request.user.username,
                kill_chrome=schedule.kill_chrome_before,
                schedule=schedule,
            )
            message = _result_text(result)
    schedules = list(Schedule.objects.select_related('folder').all())
    last_fires = {}
    for fire in ScheduleFire.objects.select_related('schedule').order_by('-fired_at')[:200]:
        last_fires.setdefault(fire.schedule_id, fire)
    open_id = ''
    if request.method == 'POST' and request.POST.get('action') in ('save', 'toggle'):
        open_id = str(request.POST.get('schedule_id') or '')
    rows = []
    for item in schedules:
        rows.append({
            'schedule': item,
            'last_fire': last_fires.get(item.id),
            'days_text': _days_text(item.days),
            'open': str(item.id) == open_id,
        })
    return render(request, 'farm_console/schedule.html', {
        'rows': rows,
        'folders': Folder.objects.order_by('name'),
        'weekdays': _weekdays(),
        'open_rules': OPEN_RULES,
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
    accounts = attach_week_sbc(list(Account.objects.all().order_by('-balance', 'email')[:300]))
    return render(request, 'farm_console/accounts.html', {
        'found': accounts,
        'missing': 0,
        'searched': False,
        'filter_presets': ACCOUNT_FILTER_PRESETS,
        'folders': Folder.objects.order_by('name'),
    })


@login_required
@require_POST
def accounts_search(request):
    email_query = (request.POST.get('email') or '').strip()
    keys = request.POST.getlist('filter_key')
    if email_query:
        conditions = conditions_from_keys(['email'], {'email': email_query})
        source = 'email'
    elif keys:
        extras = {}
        fallback = (request.POST.get('filter_extra') or '').strip()
        for key in keys:
            extras[key] = (request.POST.get('extra_%s' % key) or fallback).strip()
        conditions = conditions_from_keys(keys, extras)
        source = 'filter'
    else:
        return HttpResponse(status=204)
    if not conditions:
        return HttpResponse(status=204)
    found, missing = search_accounts(conditions)
    found.sort(key=lambda account: ((account.email or ''), account.id))
    attach_week_sbc(found)
    logger.info(
        'Поиск аккаунтов: %s %s, найдено %s',
        source,
        email_query or keys,
        len(found),
    )
    return render(request, 'farm_console/accounts_found.html', {
        'found': found,
        'missing': missing,
        'searched': True,
    })


@login_required
@require_POST
def accounts_open(request):
    worker = Worker.objects.filter(enabled=True).order_by('id').first()
    if worker is None:
        return JsonResponse({'ok': False, 'message': 'ПК выключен'})
    raw_ids = request.POST.getlist('account_id')
    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    by_id = {account.id: account for account in Account.objects.filter(id__in=ids)}
    opened = []
    for account_id in ids:
        account = by_id.get(account_id)
        if account is None:
            continue
        email = (account.email or '').strip()
        if not email:
            continue
        enqueue_open(worker, email)
        opened.append(email)
    if not opened:
        return JsonResponse({'ok': False, 'message': 'Нет email для открытия'})
    logger.info('Открытие аккаунтов с пульта: %s', opened)
    return JsonResponse({
        'ok': True,
        'message': 'Команда open поставлена: %s' % ', '.join(opened),
    })


@login_required
@require_POST
def accounts_close(request):
    worker = Worker.objects.filter(enabled=True).order_by('id').first()
    if worker is None:
        return JsonResponse({'ok': False, 'message': 'ПК выключен'})
    raw_ids = request.POST.getlist('account_id')
    ids = []
    for value in raw_ids:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    by_id = {account.id: account for account in Account.objects.filter(id__in=ids)}
    closed = []
    for account_id in ids:
        account = by_id.get(account_id)
        if account is None:
            continue
        email = (account.email or '').strip()
        if not email:
            continue
        enqueue_close(worker, email)
        closed.append(email)
    if not closed:
        return JsonResponse({'ok': False, 'message': 'Нет email для закрытия'})
    logger.info('Закрытие аккаунтов с пульта: %s', closed)
    return JsonResponse({
        'ok': True,
        'message': 'Команда close поставлена: %s' % ', '.join(closed),
    })


@login_required
@require_POST
def accounts_delete(request):
    ids = []
    for value in request.POST.getlist('account_id'):
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    accounts = list(Account.objects.filter(id__in=ids).order_by('id'))
    if not accounts:
        return JsonResponse({'ok': False, 'message': 'Ничего не выбрано'})
    emails = [(account.email or '').strip() or str(account.id) for account in accounts]
    deleted_ids = [account.id for account in accounts]
    Account.objects.filter(id__in=deleted_ids).delete()
    logger.info('Удалены аккаунты: %s', emails)
    return JsonResponse({
        'ok': True,
        'message': 'Удалено: %s' % len(deleted_ids),
        'ids': deleted_ids,
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
        elif action == 'save_market':
            message = save_market_row(
                request.POST.get('filter_id'),
                request.POST,
                request.user.username,
            )
        elif action == 'remove_market':
            message = remove_market_row(request.POST.get('filter_id'))
        elif action == 'save_snipe_form':
            message = save_snipe_form(request.POST, request.user.username)
        elif action == 'save_sbc':
            message = save_sbc_tile(
                request.POST.get('set_id'),
                request.POST.get('template_id'),
                request.POST,
                request.user.username,
            )
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    market_items = list(MarketFilter.objects.order_by('position', 'title'))
    if request.method == 'POST' and request.POST.get('action') == 'save_sbc':
        set_id = request.POST.get('set_id')
        tile_id = request.POST.get('template_id')
    else:
        set_id = request.GET.get('set')
        tile_id = request.GET.get('tile')
    snipe = SnipeSettingsDoc.current()
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
        'market_rows': [market_row_view(item) for item in market_items],
        'market_version': listing.version,
        'market_json': json.dumps(
            [{'title': item.title, 'payload': item.payload} for item in market_items],
            ensure_ascii=False,
            indent=2,
        ),
        'snipe': snipe,
        'snipe_form': snipe_form_values(snipe.payload if snipe else ''),
        'editor': selected_sbc(set_id, tile_id),
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
            modes = default_folder_modes()
            folder = Folder.objects.create(
                name=name,
                filter=applied,
                refresh_on_start=True,
                modes=modes,
                modes_text=modes_to_text(modes),
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
    members = folder_accounts(folder)
    ready, missing = accounts_for_start(folder)
    run = folder.runs.filter(state=FolderRun.STATE_ACTIVE).select_related('schedule').first()
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
    schedule = run.schedule if run is not None else None
    return {
        'folder': folder,
        'count': len(members),
        'ready': len(ready),
        'missing': missing,
        'run': run,
        'progress': progress,
        'opening': opening,
        'fail_count': fails.count(),
        'last_fail': last_fail.error_text if last_fail else '',
        'schedule': schedule,
        'days_text': _days_text(schedule.days) if schedule else '',
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


def _positive_minutes(raw, default):
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = default
    if minutes < 1:
        return 1
    return minutes


def _save_stall_minutes(minutes, silent_minutes):
    data = load_local_settings(LOCAL_SETTINGS_PATH)
    data['stall_minutes'] = minutes
    data['open_grace_sec'] = silent_minutes * 60
    data.pop('stall_kill_chrome', None)
    data.pop('page_not_loaded_close', None)
    LOCAL_SETTINGS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    settings.STALL_MINUTES = minutes
    settings.OPEN_GRACE_SEC = silent_minutes * 60


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


def _found_session_key(folder_id):
    return 'folder_found_%s' % folder_id


def _store_found(request, folder_id, found, missing):
    request.session[_found_session_key(folder_id)] = {
        'ids': [account.id for account in found],
        'missing': missing,
    }


def _load_found(request, folder_id):
    snap = request.session.get(_found_session_key(folder_id))
    if not snap:
        return [], 0, False
    ids = snap.get('ids') or []
    missing = snap.get('missing') or 0
    if not ids:
        return [], missing, True
    by_id = {
        account.id: account
        for account in Account.objects.filter(id__in=ids)
    }
    found = [by_id[item] for item in ids if item in by_id]
    return found, missing, True


def _read_days(request):
    days = []
    for item in request.POST.getlist('days'):
        if item.isdigit():
            days.append(int(item))
    return days


def _read_open(request):
    allowed = {item['key'] for item in OPEN_RULES}
    rule = request.POST.get('open_rule') or 'all'
    if rule not in allowed:
        rule = 'all'
    return rule, request.POST.get('assign_sbc') == '1'


def _weekdays():
    return (
        (0, 'пн'),
        (1, 'вт'),
        (2, 'ср'),
        (3, 'чт'),
        (4, 'пт'),
        (5, 'сб'),
        (6, 'вс'),
    )


def _days_text(days):
    labels = dict(_weekdays())
    numbers = []
    for item in list(days or []):
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if number in labels and number not in numbers:
            numbers.append(number)
    if set(numbers) == {0, 1, 2, 3, 4, 5, 6}:
        return 'каждый день'
    if not numbers:
        return 'нет дней'
    return ' '.join(labels[item] for item in numbers)


def _parse_clock(raw, fallback):
    text = (raw or '').strip()
    if not text:
        return fallback
    for fmt in ('%H:%M', '%H:%M:%S'):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return fallback
