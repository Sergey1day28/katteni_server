from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm_core', '0004_account_ea_id_optional'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='linked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='market_open',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='account',
            name='market_seen_open',
            field=models.BooleanField(default=False),
        ),
    ]
