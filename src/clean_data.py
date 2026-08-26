"""
===============================================================================
SISTEMA DE GESTIÓN DE STOCK PESCO S.A.
Módulo 1: ETL (Extract, Transform, Load) y Limpieza de Datos de Inventario
===============================================================================
Guía de Referencia / Ayuda Memoria:
- Pandas `read_excel`: Carga directa del archivo de datos fuente.
- Normalización de Nombres: Limpieza de caracteres especiales y encodings.
- `fillna`: Imputación de valores faltantes por estrategia de negocio.
- Categorías a Booleanos: Conversión de 'Y'/'N' a True/False.
- Exportación: Generación de CSV limpio en UTF-8 (compatible con Excel/Power BI).
"""

import pandas as pd
import numpy as np
import os
import sys

# Ajuste de codificación de consola para Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Definimos la ruta de nuestro archivo fuente
ruta_excel = "data_set.xlsx"

print("📥 Cargando archivo Excel...")
if not os.path.exists(ruta_excel):
    raise FileNotFoundError(f"No se encontró el archivo fuente: {ruta_excel}")

df = pd.read_excel(ruta_excel)

filas, columnas = df.shape
print(f"✅ Dataset cargado con éxito: {filas:,} filas y {columnas} columnas.")

# 2. Normalización de Nombres de Columnas y Encodings
print("\n🧹 Limpiando nombres de columnas y corrigiendo encodings...")
column_mapping = {}
for col in df.columns:
    clean_col = str(col).strip()
    if 'Paol' in clean_col:
        clean_col = clean_col.replace('Paol', 'Pañol')
    column_mapping[col] = clean_col

df.rename(columns=column_mapping, inplace=True)

# Eliminar columnas de índice innecesarias
cols_to_drop = [c for c in ['#', 'Unnamed: 30'] if c in df.columns]
if cols_to_drop:
    df.drop(columns=cols_to_drop, inplace=True)

# 3. Limpieza de Campos de Texto
df['Codigo'] = df['Codigo'].astype(str).str.strip()
df['Nombre'] = df['Nombre'].fillna('SIN DESCRIPCION').astype(str).str.strip().str.upper()
df['Grupo Articulo'] = df['Grupo Articulo'].fillna('SIN CATEGORIA').astype(str).str.strip().str.upper()

# 4. Conversión de Banderas Categóricas ('Y'/'N' -> True/False)
columnas_bandera = ['Pañol', 'Nuevos Pañol', 'Servicios', 'Calzado', 'Logistica', 'Repuestos']
for col in columnas_bandera:
    if col in df.columns:
        df[col] = (df[col] == 'Y')

# 5. Tratamiento de Campos Numéricos e Imputación de Nulos
mediana_global_leadtime = df['Lead Time'].median()
df['Lead Time'] = df['Lead Time'].fillna(df.groupby('Grupo Articulo')['Lead Time'].transform('median'))
df['Lead Time'] = df['Lead Time'].fillna(mediana_global_leadtime)

if 'Punto de Reorden' in df.columns:
    df['Punto de Reorden'] = df['Punto de Reorden'].fillna(0.0)

# 5.5 Recálculo de Disponibilidad enfocado solo en Bodega 013-PP
print("\n🔄 Recalculando disponibilidad exclusiva para Bodega 013-PP...")
df['En_Transito'] = df['SC'].fillna(0) + df['OC - PO'].fillna(0)
df['Stock Total'] = df['Stock 013-PP'].fillna(0)
df['Disponible Hoy'] = df['Stock 013-PP'].fillna(0) - (df['Comp.PC'].fillna(0) + df['Comp.OF'].fillna(0))
df['Disponible Futuro'] = df['Disponible Hoy'] + df['En_Transito']

# 5.6 Incorporar stock en tránsito inter-sucursal (bodegas T* del archivo de Stock Actual)
# Las bodegas T013-022, T022-013, etc. representan material en camino entre sucursales.
# Se detecta el archivo de stock actual automáticamente por nombre.
RUTA_STOCK_ACTUAL = "00.- Stock.xlsx"
if os.path.exists(RUTA_STOCK_ACTUAL):
    print("\n🚚 Incorporando stock en tránsito inter-sucursal desde archivo de stock...")
    try:
        df_stock = pd.read_excel(RUTA_STOCK_ACTUAL)

        # Identificar columnas necesarias
        col_bodega = next((c for c in df_stock.columns if 'Cod.Bodega' in str(c) or str(c).strip() == 'Bodega'), None)
        col_codigo = next((c for c in df_stock.columns if str(c).strip() in ['Codigo', 'Código']), None)
        col_stock  = next((c for c in df_stock.columns if str(c).strip() == 'Stock'), None)

        if col_bodega and col_codigo and col_stock:
            # Filtrar solo bodegas de tránsito (prefijo 'T')
            mask_transito = df_stock[col_bodega].astype(str).str.startswith('T', na=False)
            df_transit = df_stock[mask_transito].copy()
            df_transit[col_stock] = pd.to_numeric(df_transit[col_stock], errors='coerce').fillna(0)

            # Agrupar por código SKU y sumar unidades en tránsito
            transit_sum = (
                df_transit.groupby(col_codigo)[col_stock]
                .sum()
                .rename('Stock_Transito_Inter')
            )

            # Incorporar al dataframe principal
            df = df.merge(transit_sum, left_on='Codigo', right_index=True, how='left')
            df['Stock_Transito_Inter'] = df['Stock_Transito_Inter'].fillna(0)
            df['Disponible Futuro'] = df['Disponible Futuro'] + df['Stock_Transito_Inter']

            skus_con_transito = (df['Stock_Transito_Inter'] > 0).sum()
            total_unidades_transito = df['Stock_Transito_Inter'].sum()
            print(f"   • SKUs con stock en tránsito:  {skus_con_transito:>10,d}")
            print(f"   • Unidades totales en tránsito: {total_unidades_transito:>10,.0f} u")
            print("   ✅ Disponible Futuro actualizado con tránsito inter-sucursal.")
        else:
            df['Stock_Transito_Inter'] = 0
            print(f"   ⚠️  No se encontraron columnas esperadas en '{RUTA_STOCK_ACTUAL}'. Sin tránsito incorporado.")
            print(f"      Columnas detectadas: {list(df_stock.columns[:10])}")
    except Exception as e:
        df['Stock_Transito_Inter'] = 0
        print(f"   ⚠️  Error al leer archivo de stock: {e}")
else:
    df['Stock_Transito_Inter'] = 0
    print(f"\n⚠️  Archivo '{RUTA_STOCK_ACTUAL}' no encontrado. Sin tránsito inter-sucursal.")
    print("   Ejecute primero la carga del archivo de stock actualizado.")

# 6. Creación de Columnas Calculadas de Alerta de Negocio
print("\n🚨 Creando columnas calculadas de alerta...")
df['Estado_Stockout'] = df['Disponible Hoy'] < 0
df['Estado_Bajo_Minimo'] = (df['Disponible Hoy'] < df['Minimo']) & (df['Minimo'] > 0)
df['Estado_Sobre_Stock'] = (df['Stock Total'] > df['Maximo']) & (df['Maximo'] > 0)

# 7. Guardar Dataset Limpio en Disco
os.makedirs("data/processed", exist_ok=True)
ruta_salida = "data/processed/stock_procesado.csv"
df.to_csv(ruta_salida, index=False, encoding='utf-8-sig')

print(f"\n✅ ¡ETL Y LIMPIEZA FINALIZADA EXITOSAMENTE!")
print(f"📁 Dataset exportado en: {ruta_salida}")
