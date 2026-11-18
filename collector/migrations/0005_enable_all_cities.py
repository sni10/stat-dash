"""Collect every city of lun.ua/stat, not only Odesa (all 22 are in the dashboard's city filter).
A city can still be switched off in the admin."""
from django.db import migrations


def enable_all(apps, schema_editor):
    apps.get_model('collector', 'City').objects.update(enabled=True)


def only_odesa(apps, schema_editor):
    City = apps.get_model('collector', 'City')
    City.objects.exclude(slug='odesa').update(enabled=False)


class Migration(migrations.Migration):
    dependencies = [('collector', '0004_v_price_monthly_uah')]

    operations = [migrations.RunPython(enable_all, only_odesa)]
