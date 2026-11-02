from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('farm_core', '0009_schedule_fire_many_per_day'),
    ]

    operations = [
        migrations.AddField(
            model_name='folderrun',
            name='schedule',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='runs',
                to='farm_core.schedule',
            ),
        ),
    ]
