from datetime import datetime

from django.utils import timezone

from farm_core.bot_api import mark_stalled
from farm_core.circle import start_folder, continue_folder, stop_run
from farm_core.models import FolderRun, Schedule, ScheduleFire


def tick(now=None):
    now = now or timezone.localtime()
    local_date = now.date()
    weekday = now.weekday()
    reports = []
    mark_stalled(now=now)
    for schedule in Schedule.objects.filter(enabled=True).select_related('folder'):
        days = list(schedule.days or [])
        if days and weekday not in days:
            continue
        if _in_window(now, schedule.start_time):
            reports.append(_fire_start(schedule, local_date, now))
        if _in_window(now, schedule.stop_time):
            reports.append(_fire_stop(schedule, local_date, now))
    return [item for item in reports if item]


def _in_window(now, when):
    target = datetime.combine(now.date(), when, tzinfo=now.tzinfo)
    return abs((now - target).total_seconds()) <= 30


def _fire_start(schedule, local_date, now):
    if ScheduleFire.objects.filter(
        schedule=schedule, local_date=local_date, kind=ScheduleFire.KIND_START
    ).exists():
        return None
    if schedule.action == Schedule.ACTION_CONTINUE:
        result = continue_folder(schedule.folder, started_by='schedule')
    else:
        result = start_folder(
            schedule.folder,
            started_by='schedule',
            kill_chrome=schedule.kill_chrome_before,
        )
    fire = ScheduleFire.objects.create(
        schedule=schedule,
        local_date=local_date,
        kind=ScheduleFire.KIND_START,
        result='ok' if result.get('ok') else 'error',
        error='' if result.get('ok') else (result.get('error') or {}).get('message', ''),
    )
    del now
    return fire


def _fire_stop(schedule, local_date, now):
    if ScheduleFire.objects.filter(
        schedule=schedule, local_date=local_date, kind=ScheduleFire.KIND_STOP
    ).exists():
        return None
    run = FolderRun.objects.filter(
        folder=schedule.folder,
        state=FolderRun.STATE_ACTIVE,
    ).first()
    error = ''
    if run is not None:
        stop_run(run)
        result = 'ok'
    else:
        result = 'error'
        error = 'Нет активного круга'
    del now
    return ScheduleFire.objects.create(
        schedule=schedule,
        local_date=local_date,
        kind=ScheduleFire.KIND_STOP,
        result=result,
        error=error,
    )
