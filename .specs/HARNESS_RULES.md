# HARNESS RULES: Guardrails de Desarrollo e IA para Pesco S.A.

Vigente desde el 27-oct-2026. Reemplaza la versión anterior (Excel, bodegas "ciudad", rojo corporativo).

## Reglas obligatorias

1. **Fuente de datos = TXT del Datalake** en `data/` (SPEC-07 §1, SPEC-08). No hay carga desde
   Excel ni acceso directo a Athena. Un archivo faltante se informa y usa el respaldo de SPEC-08 §3;
   nunca se asume cero en silencio.

2. **Bodegas y zonas solo desde `apps/data_ingestion/warehouses.py`**: zona Santiago (013-xx
   físicas, central 013-PP), sucursales (002, 002-02, 003, 008, 010), y bodegas no físicas
   (tránsito, no conforme, consignación) excluidas. No se escriben listas de bodegas en otro lugar.

3. **Fórmulas = SPEC-10 a SPEC-12** y los casos dorados de SPEC-17. No se inventan nombres de campo
   ni se cambia una fórmula sin cambiar antes la spec y el test dorado.

4. **Núcleo puro**: `apps/calc/` no importa Django. Recibe números y devuelve resultados; la capa
   `apps/calculadora/` lee y escribe la BD.

5. **Cero tolerancia a la falta de pruebas**: toda función de cálculo o ingesta tiene test pytest
   en verde. `python -m pytest -q` debe pasar al 100% antes de entregar.

6. **Parámetros sin valores fijos en el código**: todo valor de negocio está en `apps/calc/params.py`
   (catálogo) y se edita desde la pantalla de parámetros con registro de cambios (SPEC-14).

7. **Nulos y ceros**: un valor vacío, NaN o inválido se convierte explícitamente a 0 antes de
   operar o guardar (`_clean_num`). Los netos de consumo negativos cuentan como 0.

8. **Estilo corporativo**: paleta `pesco-*` de `templates/base.html` (cyan `#0099DE` como color
   primario, oscuro `#0A0A0A`). El rojo se reserva para alertas y urgencias.

9. **Escritura en SAP prohibida** hasta que IT habilite Service Layer: las solicitudes se exportan
   como planilla (SPEC-13 §5).
