import logging
import time
from datetime import datetime

from django.db import close_old_connections
from django.utils import timezone

from farm_core.bot_api import mark_stalled
from farm_core.circle import start_folder, continue_folder, stop_run
from farm_core.models import FolderRun, Schedule, ScheduleFire

logger = logging.getLogger(__name__)


def run_loop(do_tick=None, sleeper=None, interval=10, max_ticks=None):
    ticks = 0
    do_tick = do_tick or tick
    sleeper = sleeper or time.sleep
    while True:
        try:
            close_old_connections()
            now = timezone.localtime()
            if ticks % 6 == 0:
                enabled = Schedule.objects.filter(enabled=True).count()
                logger.info(
                    'Часы живы, сейчас %s, включено скриптов %s',
                    now.strftime('%H:%M:%S'),
                    enabled,
                )
            fires = do_tick(now=now)
            for fire in fires or []:
                logger.info(
                    'Сработал скрипт %s %s: %s %s',
                    fire.schedule.name,
                    fire.kind,
                    fire.result,
                    fire.error,
                )
        except Exception:
            logger.exception('Тик часов упал')
            close_old_connections()
        ticks += 1
        if max_ticks is not None and ticks >= max_ticks:
            return
        sleeper(interval)


def tick(now=None):
    now = now or timezone.localtime()
    local_date = now.date()
    weekday = now.weekday()
    reports = []
    mark_stalled(now=now)
    for schedule in Schedule.objects.filter(enabled=True).select_related('folder'):
        days = _day_numbers(schedule.days)
        in_start = _in_window(now, schedule.start_time)
        in_stop = _in_window(now, schedule.stop_time)
        if weekday not in days:
            if in_start or in_stop:
                logger.info(
                    'Скрипт %s пропущен: сегодня не в днях (weekday=%s, дни=%s)',
                    schedule.name,
                    weekday,
                    days,
                )
            continue
        if in_start:
            reports.append(_fire_start(schedule, local_date, now))
        if in_stop:
            reports.append(_fire_stop(schedule, local_date, now))
    return [item for item in reports if item]


def _day_numbers(days):
    numbers = []
    for item in list(days or []):
        try:
            numbers.append(int(item))
        except (TypeError, ValueError):
            continue
    return numbers


def _in_window(now, when):
    target = datetime.combine(now.date(), when, tzinfo=now.tzinfo)
    return abs((now - target).total_seconds()) <= 30


def _fired_in_window(schedule, kind, when, now):
    last = (
        ScheduleFire.objects.filter(schedule=schedule, kind=kind)
        .order_by('-fired_at')
        .first()
    )
    if last is None:
        return False
    fired_at = last.fired_at
    if timezone.is_aware(fired_at):
        fired_at = timezone.localtime(fired_at)
    target = datetime.combine(now.date(), when, tzinfo=now.tzinfo)
    return abs((fired_at - target).total_seconds()) <= 30


def _fire_start(schedule, local_date, now):
    if _fired_in_window(schedule, ScheduleFire.KIND_START, schedule.start_time, now):
        logger.info('Скрипт %s старт уже в этом окне', schedule.name)
        return None
    if schedule.action == Schedule.ACTION_CONTINUE:
        result = continue_folder(
            schedule.folder,
            started_by='schedule',
            schedule=schedule,
        )
    else:
        result = start_folder(
            schedule.folder,
            started_by='schedule',
            kill_chrome=schedule.kill_chrome_before,
            schedule=schedule,
        )
    return ScheduleFire.objects.create(
        schedule=schedule,
        local_date=local_date,
        kind=ScheduleFire.KIND_START,
        result='ok' if result.get('ok') else 'error',
        error='' if result.get('ok') else (result.get('error') or {}).get('message', ''),
    )


def _fire_stop(schedule, local_date, now):
    if _fired_in_window(schedule, ScheduleFire.KIND_STOP, schedule.stop_time, now):
        logger.info('Скрипт %s стоп уже в этом окне', schedule.name)
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
    return ScheduleFire.objects.create(
        schedule=schedule,
        local_date=local_date,
        kind=ScheduleFire.KIND_STOP,
        result=result,
        error=error,
    )
