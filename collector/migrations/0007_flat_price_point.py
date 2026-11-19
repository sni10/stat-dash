"""lun_price_snapshot -> flat_price_point, in the naming of the other LUN tables (docs/data-model.md).
A rename, not a new table: the data stays. v_price_monthly follows the table on its own (Postgres binds views to the
table, not to its name)."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('collector', '0006_lun_raw_global_endpoints')]

    operations = [
        migrations.RenameModel('LunPriceSnapshot', 'FlatPricePoint'),
        migrations.AlterModelTable('FlatPricePoint', 'flat_price_point'),
        migrations.AlterModelOptions('FlatPricePoint', {'verbose_name': 'flat price point'}),
    ]
