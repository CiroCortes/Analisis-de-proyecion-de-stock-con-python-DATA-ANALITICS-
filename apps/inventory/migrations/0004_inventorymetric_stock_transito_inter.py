# Generated manually — agrega campo stock_transito_inter a InventoryMetric

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0003_cargastockactual_stockactual'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventorymetric',
            name='stock_transito_inter',
            field=models.IntegerField(
                default=0,
                verbose_name='Stock en Tránsito Inter-Sucursal (bodegas T*)'
            ),
        ),
    ]
