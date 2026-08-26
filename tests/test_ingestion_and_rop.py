from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import ProductSKU, Warehouse, InventoryMetric, StockProjection
from apps.data_ingestion.excel_parser import ALLOWED_WAREHOUSES, WAREHOUSE_METADATA

class IngestionAndROPTestCase(TestCase):
    def test_allowed_warehouses_includes_all_operational(self):
        """Verifica que las 9 bodegas oficiales del Stock Proyectado SAP estén configuradas."""
        self.assertIn('013-PP', ALLOWED_WAREHOUSES)
        self.assertIn('013-PS', ALLOWED_WAREHOUSES)
        self.assertIn('013-07', ALLOWED_WAREHOUSES)
        self.assertIn('013-09', ALLOWED_WAREHOUSES)
        self.assertIn('002-02', ALLOWED_WAREHOUSES)
        self.assertIn('002', ALLOWED_WAREHOUSES)
        self.assertIn('003', ALLOWED_WAREHOUSES)
        self.assertIn('008', ALLOWED_WAREHOUSES)
        self.assertIn('010', ALLOWED_WAREHOUSES)
        self.assertEqual(len(ALLOWED_WAREHOUSES), 9)


