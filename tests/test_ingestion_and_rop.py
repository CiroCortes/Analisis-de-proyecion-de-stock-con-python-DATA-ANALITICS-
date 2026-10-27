from decimal import Decimal
from django.test import TestCase
from apps.inventory.models import ProductSKU, Warehouse, InventoryMetric, StockProjection
from apps.data_ingestion.warehouses import ALLOWED_WAREHOUSES, WAREHOUSE_NAMES

class IngestionAndROPTestCase(TestCase):
    def test_allowed_warehouses_includes_all_operational(self):
        """Verifica que las 10 bodegas oficiales del Stock Proyectado SAP estén configuradas."""
        self.assertIn('013-PP', ALLOWED_WAREHOUSES)
        self.assertIn('013-PS', ALLOWED_WAREHOUSES)
        self.assertIn('013-07', ALLOWED_WAREHOUSES)
        self.assertIn('013-09', ALLOWED_WAREHOUSES)
        self.assertIn('013-03', ALLOWED_WAREHOUSES)
        self.assertIn('002-02', ALLOWED_WAREHOUSES)
        self.assertIn('002', ALLOWED_WAREHOUSES)
        self.assertIn('003', ALLOWED_WAREHOUSES)
        self.assertIn('008', ALLOWED_WAREHOUSES)
        self.assertIn('010', ALLOWED_WAREHOUSES)
        self.assertEqual(len(ALLOWED_WAREHOUSES), 10)




class SCAndROPRecalcTestCase(TestCase):
    def setUp(self):
        self.wh = Warehouse.objects.create(code='013-PP', name='Central')
        self.sku = ProductSKU.objects.create(code='SKU1', description='x', lead_time_days=30)

    def test_scs_loader_sums_open_pending_by_sku_wh(self):
        import os, tempfile
        from apps.data_ingestion.datalake_ingest import ingest_datalake_scs
        content = (
            "|nro_sc_sap|bodega_solicitada|codigo_sku|fecha_solicitud|cantidad_solicitada|cantidad_pendiente_sc|\n"
            "|---|---|---|---|---|---|\n"
            "|1|013-PP|SKU1|2026-10-01|10|6|\n"
            "|2|013-PP|SKU1|2026-10-02|5|5|\n"
            "|3||SKU1|2026-10-02|4|4|\n"
            "|4|013-PP|NOEXISTE|2026-10-02|9|9|\n"
        )
        with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write(content)
        try:
            self.assertEqual(dict(ingest_datalake_scs(f.name)), {('SKU1', '013-PP'): 15})
        finally:
            os.unlink(f.name)

    def test_scs_loader_missing_file_returns_empty(self):
        from apps.data_ingestion.datalake_ingest import ingest_datalake_scs
        self.assertEqual(ingest_datalake_scs('no_existe.txt'), {})

    def test_drp_recalculates_rop_instead_of_reusing_previous_run(self):
        from apps.inventory.models import SKUClassification
        from apps.inventory.classification_engine import run_drp_engine
        InventoryMetric.objects.create(product=self.sku, warehouse=self.wh, stock_physical=0, disp_future=0)
        SKUClassification.objects.create(
            product=self.sku, repo_category='R', rop_statistical=10,
            avg_daily_demand=Decimal('1'),
        )
        run_drp_engine()
        self.assertEqual(StockProjection.objects.get(product=self.sku).rop, 10)

        SKUClassification.objects.filter(product=self.sku).update(rop_statistical=25)
        run_drp_engine()
        self.assertEqual(StockProjection.objects.get(product=self.sku).rop, 25)


class EnsureWarehousesTestCase(TestCase):
    def test_creates_all_official_warehouses_from_empty_db(self):
        from apps.data_ingestion.datalake_ingest import ensure_warehouses
        ensure_warehouses()
        self.assertEqual(set(Warehouse.objects.values_list('code', flat=True)), set(ALLOWED_WAREHOUSES))

    def test_does_not_reactivate_excluded_warehouse(self):
        from apps.data_ingestion.datalake_ingest import ensure_warehouses
        Warehouse.objects.create(code='008', name='x', is_active=False)
        ensure_warehouses()
        wh = Warehouse.objects.get(code='008')
        self.assertFalse(wh.is_active)
        self.assertEqual(wh.name, WAREHOUSE_NAMES['008'])
