from django.db import migrations, models


def always_kill_chrome(apps, schema_editor):
    Schedule = apps.get_model('farm_core', 'Schedule')
    Schedule.objects.filter(kill_chrome_before=False).update(kill_chrome_before=True)


class Migration(migrations.Migration):
    dependencies = [
        ('farm_core', '0007_folder_assign_sbc'),
    ]

    operations = [
        migrations.AlterField(
            model_name='schedule',
            name='kill_chrome_before',
            field=models.BooleanField(default=True),
        ),
        migrations.RunPython(always_kill_chrome, migrations.RunPython.noop),
    ]
