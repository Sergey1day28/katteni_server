from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ('farm_core', '0008_schedule_kill_chrome_default'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='schedulefire',
            name='schedule_fire_unique',
        ),
    ]
