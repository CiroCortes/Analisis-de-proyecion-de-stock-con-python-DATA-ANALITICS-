"""
===============================================================================
SISTEMA DE GESTIÓN DE STOCK PESCO S.A.
Módulo 4: Modelo de Proyección de Inventario y Cálculo de Punto de Reorden (ROP)
===============================================================================
Guía de Referencia / Ayuda Memoria:
- Fórmula ROP: ROP = (Demanda Diaria * Lead Time) + Stock de Seguridad.
- Safety Stock: Stock_Seguridad = Z * Demanda_Diaria * sqrt(Lead Time).
- Segmentación: Clasificación de SKUs activos vs inactivos (Demanda = 0 si no hay movimiento).
- Sugerido a Comprar: Cálculo de la brecha entre la meta (Máximo) y la disponibilidad real.
"""

import pandas as pd
import numpy as np
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Cargamos el dataset procesado
ruta_csv = "data/processed/stock_procesado.csv"
print("📥 Cargando dataset para Proyección de Inventario...")
df = pd.read_csv(ruta_csv)

# 2. Estimación de Demanda Diaria Segmentada
demanda_total = df['Comp.PC'] + df['Comp.OF']

condiciones = [
    (demanda_total > 0),
    (df['Stock Total'] > 0)
]
elecciones = [
    demanda_total / 30.0,
    0.02
]
df['Demanda_Diaria'] = np.select(condiciones, elecciones, default=0.0)

# 3. Cálculo del Stock de Seguridad (Nivel de Servicio 95% -> Z = 1.65)
Z = 1.65
df['Stock_Seguridad'] = np.where(
    df['Demanda_Diaria'] > 0,
    Z * df['Demanda_Diaria'] * np.sqrt(df['Lead Time']),
    0.0
)

# 4. Cálculo del Punto de Reorden (ROP)
df['Punto_de_Reorden_Calculado'] = np.where(
    df['Demanda_Diaria'] > 0,
    (df['Demanda_Diaria'] * df['Lead Time']) + df['Stock_Seguridad'],
    0.0
)
df['Punto_de_Reorden_Calculado'] = df['Punto_de_Reorden_Calculado'].round(2)

# 5. Generar Alerta de Recompra Solo para SKUs con Demanda Real
df['Alerta_Recompra'] = (df['Disponible Futuro'] < df['Punto_de_Reorden_Calculado']) & (df['Demanda_Diaria'] > 0)

# 6. Sugerido de Compra Refinado
def calcular_compra_sugerida(row):
    if row['Alerta_Recompra']:
        meta = row['Maximo'] if row['Maximo'] > 0 else (row['Punto_de_Reorden_Calculado'] * 1.5)
        faltante = meta - row['Disponible Futuro']
        return max(1.0, round(faltante, 0))
    return 0.0

df['Sugerido_Comprar'] = df.apply(calcular_compra_sugerida, axis=1)

# 7. Resumen de Resultados del Algoritmo Refinado
skus_comprar = (df['Alerta_Recompra']).sum()
total_unidades_comprar = df['Sugerido_Comprar'].sum()
skus_inactivos = (df['Demanda_Diaria'] == 0).sum()

print("\n" + "="*65)
print("      🔮 RESULTADOS DEL MODELO ROP REFINADO Y SEGMENTADO")
print("="*65)
print(f"  • Total SKUs Evaluados:                  {len(df):>15,d}")
print(f"  • SKUs Inactivos / Sin Movimiento:       {skus_inactivos:>15,d}  ({skus_inactivos/len(df)*100:.1f}%)")
print(f"  • SKUs que requieren Orden de Compra:    {skus_comprar:>15,d}  ({skus_comprar/len(df)*100:.1f}%)")
print(f"  • Total Unidades Sugeridas a Comprar:    {total_unidades_comprar:>15,.0f} u")
print("="*65)
"""
===============================================================================
SISTEMA DE GESTIÓN DE STOCK PESCO S.A.
Módulo 4: Modelo de Proyección de Inventario y Cálculo de Punto de Reorden (ROP)
===============================================================================
Guía de Referencia / Ayuda Memoria:
- Fórmula ROP: ROP = (Demanda Diaria * Lead Time) + Stock de Seguridad.
- Safety Stock: Stock_Seguridad = Z * Demanda_Diaria * sqrt(Lead Time).
- Segmentación: Clasificación de SKUs activos vs inactivos (Demanda = 0 si no hay movimiento).
- Sugerido a Comprar: Cálculo de la brecha entre la meta (Máximo) y la disponibilidad real.
"""

import pandas as pd
import numpy as np
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Cargamos el dataset procesado
ruta_csv = "data/processed/stock_procesado.csv"
print("📥 Cargando dataset para Proyección de Inventario...")
df = pd.read_csv(ruta_csv)

# 2. Estimación de Demanda Diaria Segmentada
demanda_total = df['Comp.PC'] + df['Comp.OF']

condiciones = [
    (demanda_total > 0),
    (df['Stock Total'] > 0)
]
elecciones = [
    demanda_total / 30.0,
    0.02
]
df['Demanda_Diaria'] = np.select(condiciones, elecciones, default=0.0)

# 3. Cálculo del Stock de Seguridad (Nivel de Servicio 95% -> Z = 1.65)
Z = 1.65
df['Stock_Seguridad'] = np.where(
    df['Demanda_Diaria'] > 0,
    Z * df['Demanda_Diaria'] * np.sqrt(df['Lead Time']),
    0.0
)

# 4. Cálculo del Punto de Reorden (ROP)
df['Punto_de_Reorden_Calculado'] = np.where(
    df['Demanda_Diaria'] > 0,
    (df['Demanda_Diaria'] * df['Lead Time']) + df['Stock_Seguridad'],
    0.0
)
df['Punto_de_Reorden_Calculado'] = df['Punto_de_Reorden_Calculado'].round(2)

# 5. Generar Alerta de Recompra Solo para SKUs con Demanda Real
df['Alerta_Recompra'] = (df['Disponible Futuro'] < df['Punto_de_Reorden_Calculado']) & (df['Demanda_Diaria'] > 0)

# 6. Sugerido de Compra Refinado
def calcular_compra_sugerida(row):
    if row['Alerta_Recompra']:
        meta = row['Maximo'] if row['Maximo'] > 0 else (row['Punto_de_Reorden_Calculado'] * 1.5)
        faltante = meta - row['Disponible Futuro']
        return max(1.0, round(faltante, 0))
    return 0.0

df['Sugerido_Comprar'] = df.apply(calcular_compra_sugerida, axis=1)

# 7. Resumen de Resultados del Algoritmo Refinado
skus_comprar = (df['Alerta_Recompra']).sum()
total_unidades_comprar = df['Sugerido_Comprar'].sum()
skus_inactivos = (df['Demanda_Diaria'] == 0).sum()

print("\n" + "="*65)
print("      🔮 RESULTADOS DEL MODELO ROP REFINADO Y SEGMENTADO")
print("="*65)
print(f"  • Total SKUs Evaluados:                  {len(df):>15,d}")
print(f"  • SKUs Inactivos / Sin Movimiento:       {skus_inactivos:>15,d}  ({skus_inactivos/len(df)*100:.1f}%)")
print(f"  • SKUs que requieren Orden de Compra:    {skus_comprar:>15,d}  ({skus_comprar/len(df)*100:.1f}%)")
print(f"  • Total Unidades Sugeridas a Comprar:    {total_unidades_comprar:>15,.0f} u")
print("="*65)

# 8. Exportar Dataset Enriquecido (CSV General)
ruta_salida = "data/processed/stock_proyectado.csv"
df.to_csv(ruta_salida, index=False, encoding='utf-8-sig')
print(f"\n✅ Dataset enriquecido exportado en: {ruta_salida}")

# 9. Exportar Reporte Específico de Compras 013-PP (Excel)
df_compras = df[df['Sugerido_Comprar'] > 0].copy()
df_compras['Bodega_Destino'] = '013-PP'

columnas_reporte = [
    'Codigo', 'Nombre', 'Grupo Articulo', 'Bodega_Destino', 'Lead Time',
    'Disponible Hoy', 'En_Transito', 'Disponible Futuro',
    'Minimo', 'Maximo', 'Punto_de_Reorden_Calculado', 'Sugerido_Comprar'
]
columnas_presentes = [c for c in columnas_reporte if c in df_compras.columns]
df_compras = df_compras[columnas_presentes].sort_values(by='Sugerido_Comprar', ascending=False)

ruta_excel = "data/processed/reporte_compras_013_pp.xlsx"
df_compras.to_excel(ruta_excel, index=False, engine='openpyxl')
print(f"✅ Reporte de compras Excel (solo pendientes) generado en: {ruta_excel}")
