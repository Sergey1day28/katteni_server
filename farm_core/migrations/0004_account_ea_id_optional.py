from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farm_core', '0003_remove_rent'),
    ]

    operations = [
        migrations.AlterField(
            model_name='account',
            name='ea_account_id',
            field=models.IntegerField(blank=True, null=True, unique=True),
        ),
    ]
