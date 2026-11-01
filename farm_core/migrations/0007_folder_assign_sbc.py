from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('farm_core', '0006_folder_open_rule'),
    ]

    operations = [
        migrations.AddField(
            model_name='folder',
            name='assign_sbc',
            field=models.BooleanField(default=False),
        ),
    ]
