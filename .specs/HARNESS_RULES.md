# HARNESS RULES: Guardrails de Desarrollo e IA para Pesco S.A.

## ⚠️ Reglas Obligatorias de Cumplimiento Técnico (Arnés)

1. **PROHIBIDO procesar bodegas de tipo Ciudad**:
   - `Stock Antofagasta`, `Stock Calama`, `Stock Copiapo`, `Stock Los Angeles`, `Stock Puerto Montt` NUNCA deben crearse como modelos de bodega ni incluirse en los resúmenes.

2. **CERO tolerancias a mutación de fórmulas ROP**:
   - El cálculo de ROP y Disponible Futuro DEBE seguir estrictamente las definiciones de `SPEC-02`. No se pueden inventar nombres de variables o cambiar la lógica de la resta de compromisos.

3. **CERO tolerancias a la falta de Pruebas**:
   - Toda función de ingestión o cálculo de ROP debe tener un test unitario en `pytest` que pase en verde (100% de éxito).

4. **Estilo Corporativo Pesco**:
   - El color primario es el Rojo Corporativo Pesco. No utilizar paletas azules genéricas o tonos pastel no alineados.

5. **Tratamiento de Nulos y Ceros**:
   - Si una métrica en el Excel viene vacía o NaN, DEBE convertirse explícitamente a 0 entero/decimal antes de operar en la BD.
