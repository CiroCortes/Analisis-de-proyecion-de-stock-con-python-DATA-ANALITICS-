> **OBSOLETO (27-oct-2026).** Describe el motor anterior (ROP por bodega, DPD, lista fija de
> bodegas). Lo reemplazan SPEC-10 (motor de cálculo), SPEC-11 (red y distribución) y SPEC-07
> (bodegas). Se conserva como referencia histórica.

# SPEC-02: Reglas de Negocio ROP y Algoritmo de Proyección

## 1. Reglas Generales
1. **Filtro Estricto de Bodegas**:
   - Solamente se deben procesar las bodegas cuyo código coincida con la lista oficial:
     `['013-PP', '013-PS', '013-07', '013-09', '002', '002-02', '003', '008', '010']`.
   - CUALQUIER columna que empiece por "Stock <Ciudad>" (ej. Antofagasta, Calama, etc.) DEBE SER IGNORADA.

2. **Cálculo de Disponible Futuro**:
   - `Disponible Futuro = Disponible Hoy + SC + OC_PO - Comp.PC - Comp.OF`

3. **Cálculo de Punto de Reorden (ROP)**:
   - `Demanda Promedio Diaria (DPD) = (Comp.PC + Comp.OF) / 30` (o período configurable)
   - `Stock de Seguridad (SS) = DPD * Factor_Seguridad (ej. 7 días)`
   - `Punto de Reorden (ROP) = (DPD * Lead_Time_Days) + SS`

4. **Sugerido de Compra**:
   - Si `Disponible Futuro < ROP`:
     - `Unidades a Comprar = ROP - Disponible Futuro`
     - Si `Disponible Futuro <= 0`:
       - `Nivel Urgencia = URGENTE`
       - `Quiebre Unidades = abs(Disponible Futuro)`
     - Si `Disponible Futuro > 0`:
       - `Nivel Urgencia = MEDIO`
       - `Quiebre Unidades = ROP - Disponible Futuro`
   - Si `Disponible Futuro >= ROP`:
     - `Unidades a Comprar = 0`
     - `Nivel Urgencia = NORMAL`
     - `Quiebre Unidades = 0`

5. **Quiebre en USD**:
   - `Quiebre USD = Quiebre Unidades * Unit_Cost_USD`
