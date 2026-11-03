from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm_core', '0011_schedule_open_rule'),
    ]

    operations = [
        migrations.AddField(
            model_name='accountloginsecret',
            name='ea_password',
            field=models.CharField(blank=True, max_length=150),
        ),
    ]
