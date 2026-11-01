from django.db import migrations


def merge_snipe_docs(apps, schema_editor):
    del schema_editor
    Doc = apps.get_model('farm_core', 'SnipeSettingsDoc')
    docs = list(Doc.objects.order_by('-updated_at', '-id'))
    if len(docs) > 1:
        keep_id = docs[0].pk
        Doc.objects.exclude(pk=keep_id).delete()


def strip_rent_filters(apps, schema_editor):
    del schema_editor
    Folder = apps.get_model('farm_core', 'Folder')
    for folder in Folder.objects.all():
        conditions = list(folder.filter or [])
        cleaned = [item for item in conditions if item.get('field') != 'rent']
        if cleaned != conditions:
            folder.filter = cleaned
            folder.save(update_fields=['filter'])


class Migration(migrations.Migration):

    dependencies = [
        ('farm_core', '0002_botsession'),
    ]

    operations = [
        migrations.RunPython(merge_snipe_docs, migrations.RunPython.noop),
        migrations.RunPython(strip_rent_filters, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='account',
            name='rent',
        ),
        migrations.RemoveField(
            model_name='snipesettingsdoc',
            name='rent_group',
        ),
    ]
