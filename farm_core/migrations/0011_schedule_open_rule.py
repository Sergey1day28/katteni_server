from django.db import migrations, models


def copy_folder_rules(apps, schema_editor):
    Schedule = apps.get_model('farm_core', 'Schedule')
    for schedule in Schedule.objects.select_related('folder').iterator():
        schedule.open_rule = schedule.folder.open_rule or 'all'
        schedule.assign_sbc = bool(schedule.folder.assign_sbc)
        schedule.save(update_fields=['open_rule', 'assign_sbc'])


class Migration(migrations.Migration):
    dependencies = [
        ('farm_core', '0010_folderrun_schedule'),
    ]

    operations = [
        migrations.AddField(
            model_name='schedule',
            name='assign_sbc',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='schedule',
            name='open_rule',
            field=models.CharField(default='all', max_length=32),
        ),
        migrations.RunPython(copy_folder_rules, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='folder',
            name='assign_sbc',
        ),
        migrations.RemoveField(
            model_name='folder',
            name='open_rule',
        ),
    ]
