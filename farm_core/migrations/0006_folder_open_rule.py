from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('farm_core', '0005_account_linked_and_market'),
    ]

    operations = [
        migrations.AddField(
            model_name='folder',
            name='open_rule',
            field=models.CharField(default='all', max_length=32),
        ),
    ]
