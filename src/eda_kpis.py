"""
===============================================================================
SISTEMA DE GESTIÓN DE STOCK PESCO S.A.
Módulo 2: Análisis Exploratorio de Datos (EDA) y KPIs de Inventario
===============================================================================
Guía de Referencia / Ayuda Memoria:
- `len(df)` y `.sum()`: Métricas globales de volumen y quiebre.
- `.groupby('Grupo Articulo')`: Segmentación por categoría de producto.
- `reset_index()`: Conversión de agrupaciones a DataFrames estructurados.
- `sort_values(ascending=False)`: Ranking de sucursales y categorías críticas.
"""

import pandas as pd
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Cargamos el dataset procesado
ruta_csv = "data/processed/stock_procesado.csv"
print("📊 Cargando datos procesados...")
df = pd.read_csv(ruta_csv)

# 2. Métricas Globales de Negocio
total_skus = len(df)
total_stock_fisico = df['Stock Total'].sum()
total_disp_hoy = df['Disponible Hoy'].sum()
total_disp_futuro = df['Disponible Futuro'].sum()

# 3. Conteo de Alertas
skus_quiebre = df['Estado_Stockout'].sum()
skus_bajo_minimo = df['Estado_Bajo_Minimo'].sum()
skus_sobre_stock = df['Estado_Sobre_Stock'].sum()

comp_clientes = df['Comp.PC'].sum()
comp_fabricacion = df['Comp.OF'].sum()
solicitudes_compra = df['SC'].sum()
ordenes_compra_po = df['OC - PO'].sum()

# 4. Imprimir Reporte Ejecutivo en Consola
print("\n" + "="*65)
print("      📈 RESUMEN EJECUTIVO Y KPIS GLOBALES DE INVENTARIO (PESCO)")
print("="*65)
print(f"  • Total SKUs Evaluados:                  {total_skus:>15,d}")
print(f"  • Stock Físico Total (Unidades):          {total_stock_fisico:>15,.0f}")
print(f"  • Disponible Hoy Total (Unidades):        {total_disp_hoy:>15,.0f}")
print(f"  • Disponible Futuro (Unidades):           {total_disp_futuro:>15,.0f}")
print("-" * 65)
print(f"  • SKUs en Quiebre / Déficit (Hoy < 0):   {skus_quiebre:>15,d}  ({skus_quiebre/total_skus*100:.1f}%)")
print(f"  • SKUs Bajo Stock Mínimo:                {skus_bajo_minimo:>15,d}  ({skus_bajo_minimo/total_skus*100:.1f}%)")
print(f"  • SKUs en Sobre-Stock (Total > Máx):     {skus_sobre_stock:>15,d}  ({skus_sobre_stock/total_skus*100:.1f}%)")
print("-" * 65)
print(f"  • Compromisos Pedidos Clientes (Comp.PC): {comp_clientes:>15,.0f} u")
print(f"  • Compromisos Fabricación (Comp.OF):     {comp_fabricacion:>15,.0f} u")
print(f"  • Solicitudes de Compra Activas (SC):     {solicitudes_compra:>15,.0f} u")
print(f"  • Órdenes de Compra en Tránsito (PO):    {ordenes_compra_po:>15,.0f} u")
print("="*65)

# 5. Distribución de Stock Físico por Sucursal / Bodega
print("\n🏢 DISTRIBUCIÓN DE STOCK POR BODEGA / SUCURSAL:")

bodegas = [
    'Stock Antofagasta', 'Stock Calama', 'Stock Copiapo', 'Stock Los Angeles', 
    'Stock Puerto Montt', 'Stock 013-07', 'Stock 013-09', 'Stock 013-PS', 'Stock 013-PP'
]

stock_por_bodega = df[bodegas].sum().reset_index()
stock_por_bodega.columns = ['Bodega', 'Stock_Unidades']
stock_por_bodega['Bodega'] = stock_por_bodega['Bodega'].str.replace('Stock ', '')
stock_por_bodega['%_del_Total'] = (stock_por_bodega['Stock_Unidades'] / total_stock_fisico) * 100
stock_por_bodega = stock_por_bodega.sort_values(by='Stock_Unidades', ascending=False)

for _, fila in stock_por_bodega.iterrows():
    print(f"  • {fila['Bodega']:<20}: {fila['Stock_Unidades']:>12,.0f} u  ({fila['%_del_Total']:>5.1f}%)")

# 6. Top 10 Categorías de Productos con Mayor Cantidad de Quiebres
print("\n⚠️ TOP 10 CATEGORÍAS CON MAYOR QUIEBRE DE STOCK (ALERTA ROJA):")

top_quiebres = df[df['Estado_Stockout']].groupby('Grupo Articulo').size().reset_index(name='SKUs_En_Quiebre')
top_quiebres = top_quiebres.sort_values(by='SKUs_En_Quiebre', ascending=False).head(10)

for _, fila in top_quiebres.iterrows():
    print(f"  • {fila['Grupo Articulo']:<35}: {fila['SKUs_En_Quiebre']:>5,d} SKUs")
