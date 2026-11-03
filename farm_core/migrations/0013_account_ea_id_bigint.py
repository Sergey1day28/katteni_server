from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm_core', '0012_accountloginsecret_ea_password'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='ea_account_id',
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
    ]
