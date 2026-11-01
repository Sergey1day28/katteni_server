from farm_core.models import DailyMetric


def put_daily_metric(account, date, name, value):
    metric, created = DailyMetric.objects.get_or_create(
        account=account,
        date=date,
        name=name,
        defaults={'value': value},
    )
    if not created:
        metric.value = value
        metric.save(update_fields=['value', 'updated_at'])
    return metric
