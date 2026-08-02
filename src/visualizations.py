"""
===============================================================================
SISTEMA DE GESTIÓN DE STOCK PESCO S.A.
Módulo 3: Generación de Visualizaciones Ejecutivas y Gráficos Estadísticos
===============================================================================
Guía de Referencia / Ayuda Memoria:
- `sns.set_theme(style="whitegrid")`: Aplicación de plantilla estética corporativa.
- `ax.barh(...)`: Gráficos de barras horizontales optimizados para etiquetas largas.
- `sns.scatterplot(...)`: Matriz 2D de dispersión para detectar cuadrantes de riesgo.
- `plt.savefig(..., dpi=300)`: Exportación a imágenes PNG de alta resolución.
"""

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Cargamos el dataset procesado
ruta_csv = "data/processed/stock_procesado.csv"
print("🎨 Cargando datos para visualización...")
df = pd.read_csv(ruta_csv)

# 2. Creamos la carpeta donde se guardarán las imágenes de los gráficos
carpeta_figuras = "reports/figures"
os.makedirs(carpeta_figuras, exist_ok=True)

# 3. Configuración del Estilo Visual Profesional (Seaborn + Matplotlib)
sns.set_theme(style="whitegrid")
plt.rcParams['font.sans-serif'] = 'Arial'
plt.rcParams['axes.edgecolor'] = '#cccccc'
plt.rcParams['axes.linewidth'] = 0.8

# -----------------------------------------------------------------------------
# GRÁFICO 1: Distribución de Stock Físico por Sucursal / Bodega
# -----------------------------------------------------------------------------
print("📈 Generando Gráfico 1: Stock por Bodega...")

bodegas = [
    'Stock Antofagasta', 'Stock Calama', 'Stock Copiapo', 'Stock Los Angeles', 
    'Stock Puerto Montt', 'Stock 013-07', 'Stock 013-09', 'Stock 013-PS', 'Stock 013-PP'
]

df_bodegas = df[bodegas].sum().reset_index()
df_bodegas.columns = ['Bodega', 'Unidades']
df_bodegas['Bodega'] = df_bodegas['Bodega'].str.replace('Stock ', '')
df_bodegas = df_bodegas.sort_values(by='Unidades', ascending=True)

fig, ax = plt.subplots(figsize=(10, 6))
barras = ax.barh(df_bodegas['Bodega'], df_bodegas['Unidades'], color='#1f77b4', edgecolor='none', height=0.65)

for barra in barras:
    ancho = barra.get_width()
    ax.annotate(
        f'{ancho:,.0f} u',
        xy=(ancho, barra.get_y() + barra.get_height() / 2),
        xytext=(5, 0),
        textcoords="offset points",
        ha='left', va='center',
        fontsize=10, fontweight='bold', color='#333333'
    )

ax.set_title('Distribución de Stock Físico por Sucursal / Bodega (Unidades)', fontsize=14, fontweight='bold', pad=15)
ax.set_xlabel('Unidades Físicas Almacenadas', fontsize=11, labelpad=10)
ax.set_ylabel('Sucursal / Bodega', fontsize=11)
ax.set_xlim(0, df_bodegas['Unidades'].max() * 1.15)

plt.tight_layout()
ruta_grafico1 = os.path.join(carpeta_figuras, "stock_por_bodega.png")
plt.savefig(ruta_grafico1, dpi=300, bbox_inches='tight')
plt.close()

print(f"✅ Gráfico 1 guardado con éxito en: {ruta_grafico1}")

# -----------------------------------------------------------------------------
# GRÁFICO 2: Top 10 Categorías con Mayor Quiebre de Stock (Alerta Roja)
# -----------------------------------------------------------------------------
print("📈 Generando Gráfico 2: Top Categorías en Quiebre...")

df_quiebres = df[df['Estado_Stockout']].groupby('Grupo Articulo').size().reset_index(name='SKUs_Quiebre')
df_quiebres = df_quiebres.sort_values(by='SKUs_Quiebre', ascending=True).tail(10)

fig, ax = plt.subplots(figsize=(10, 6))
barras = ax.barh(df_quiebres['Grupo Articulo'], df_quiebres['SKUs_Quiebre'], color='#d62728', height=0.65)

for barra in barras:
    ancho = barra.get_width()
    ax.annotate(
        f'{ancho:,} SKUs',
        xy=(ancho, barra.get_y() + barra.get_height() / 2),
        xytext=(5, 0),
        textcoords="offset points",
        ha='left', va='center',
        fontsize=10, fontweight='bold', color='#800000'
    )

ax.set_title('Top 10 Categorías con Mayor Quiebre de Stock (SKUs en Déficit)', fontsize=14, fontweight='bold', pad=15)
ax.set_xlabel('Cantidad de SKUs con Stockout (Disponible Hoy < 0)', fontsize=11, labelpad=10)
ax.set_ylabel('Categoría / Grupo Artículo', fontsize=11)
ax.set_xlim(0, df_quiebres['SKUs_Quiebre'].max() * 1.15)

plt.tight_layout()
ruta_grafico2 = os.path.join(carpeta_figuras, "top_quiebres_categoria.png")
plt.savefig(ruta_grafico2, dpi=300, bbox_inches='tight')
plt.close()

print(f"✅ Gráfico 2 guardado con éxito en: {ruta_grafico2}")

# -----------------------------------------------------------------------------
# GRÁFICO 3 MEJORADO: Matriz de Riesgo con Zonas Explicativas para Gerencia
# -----------------------------------------------------------------------------
print("📈 Generando Gráfico 3 Mejorado: Matriz de Riesgo con Zonas Explicativas...")

df_matriz = df[(df['Minimo'] > 0) & (df['Minimo'] <= 500) & (df['Disponible Hoy'] <= 500)].copy()

fig, ax = plt.subplots(figsize=(11, 7))

# Zona de alerta roja de fondo (Disponible < 0)
ax.axhspan(-350, 0, color='#ffcccc', alpha=0.45, label='Zona Crítica (Déficit / Quiebre)')

sns.scatterplot(
    data=df_matriz,
    x='Minimo',
    y='Disponible Hoy',
    hue='Estado_Stockout',
    palette={True: '#d62728', False: '#1f77b4'},
    alpha=0.7,
    s=60,
    ax=ax
)

max_val = max(df_matriz['Minimo'].max(), df_matriz['Disponible Hoy'].max())
ax.plot([0, max_val], [0, max_val], color='#ff7f0e', linestyle='--', linewidth=2, label='Política Stock Mínimo (Y = X)')
ax.axhline(0, color='black', linewidth=1.2, linestyle='-')

ax.text(
    250, -250, 
    'ZONA DE QUIEBRE CRÍTICO\n(Deuda de Repuestos en Taller)', 
    fontsize=10, fontweight='bold', color='#900c3f', 
    bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#900c3f", lw=1.5)
)

ax.text(
    50, 380, 
    'ZONA DE STOCK SALUDABLE\n(Inventario por encima del mínimo)', 
    fontsize=10, fontweight='bold', color='#1e8449', 
    bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#1e8449", lw=1.5)
)

ax.set_title('Matriz de Riesgo de Inventario: Disponible Hoy vs Stock Mínimo', fontsize=14, fontweight='bold', pad=15)
ax.set_xlabel('Stock Mínimo Configurado en ERP (Unidades)', fontsize=11, labelpad=10)
ax.set_ylabel('Disponible Hoy Real en Bodega (Unidades)', fontsize=11)
ax.set_ylim(-320, 500)

handles, labels = ax.get_legend_handles_labels()
ax.legend(loc='upper right', frameon=True, facecolor='white', framealpha=0.9)

plt.tight_layout()
ruta_grafico3 = os.path.join(carpeta_figuras, "matriz_riesgo_stock.png")
plt.savefig(ruta_grafico3, dpi=300, bbox_inches='tight')
plt.close()

print(f"✅ Gráfico 3 Mejorado guardado con éxito en: {ruta_grafico3}")
