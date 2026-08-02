"""
===============================================================================
SISTEMA DE GESTIÓN DE STOCK PESCO S.A.
Módulo 5: Generación Automatizada de Reporte PDF Ejecutivo (ReportLab)
===============================================================================
Guía de Referencia / Ayuda Memoria:
- `SimpleDocTemplate`: Estructura base del lienzo del documento PDF.
- `ParagraphStyle` y `TableStyle`: Formateo estético corporativo.
- `PageBreak()`: Saltos de página estratégicos para diseño limpio.
- `doc.build(story)`: Compilación automatizada de elementos en un PDF listo para imprimir.
"""

import pandas as pd
import os
import sys

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8')

# 1. Cargamos el dataset proyectado
ruta_csv = "data/processed/stock_proyectado.csv"
print("📄 Cargando datos para la generación del PDF...")
df = pd.read_csv(ruta_csv)

# 2. Definimos la carpeta y ruta del PDF de salida
os.makedirs("reports", exist_ok=True)
ruta_pdf = "reports/Reporte_Ejecutivo_Inventario_Pesco.pdf"

print(f"⚙️ Construyendo documento PDF en: {ruta_pdf}...")

# 3. Lienzo del Documento PDF (Tamaño Carta)
doc = SimpleDocTemplate(
    ruta_pdf,
    pagesize=letter,
    rightMargin=36, leftMargin=36,
    topMargin=36, bottomMargin=36
)

# 4. Estilos de Texto
styles = getSampleStyleSheet()

titulo_style = ParagraphStyle(
    'TituloEmpresarial',
    parent=styles['Heading1'],
    fontName='Helvetica-Bold',
    fontSize=20,
    textColor=colors.HexColor('#1f77b4'),
    spaceAfter=10
)

subtitulo_style = ParagraphStyle(
    'SubtituloEmpresarial',
    parent=styles['Normal'],
    fontName='Helvetica',
    fontSize=11,
    textColor=colors.HexColor('#555555'),
    spaceAfter=20
)

seccion_style = ParagraphStyle(
    'SeccionHeading',
    parent=styles['Heading2'],
    fontName='Helvetica-Bold',
    fontSize=14,
    textColor=colors.HexColor('#333333'),
    spaceBefore=15,
    spaceAfter=10
)

# 5. Lista donde iremos agregando los elementos del PDF (Story)
story = []

# --- ENCABEZADO ---
story.append(Paragraph("PESCO S.A. - INFORME EJECUTIVO DE INVENTARIO Y ROP", titulo_style))
story.append(Paragraph("<i>Diagnóstico automatizado de stock, quiebres y proyección de recompras prioritarias</i>", subtitulo_style))
story.append(Spacer(1, 10))

# --- TABLA DE KPIS MACRO ---
print("📊 Agregando Tabla de KPIs Macro...")
total_skus = len(df)
skus_quiebre = (df['Estado_Stockout']).sum()
skus_comprar = (df['Alerta_Recompra']).sum()
unidades_comprar = df['Sugerido_Comprar'].sum()

datos_kpi = [
    ['Métrica Evaluada', 'Valor Observado', '% del Total', 'Estado / Impacto'],
    ['Total SKUs Auditados', f'{total_skus:,}', '100.0%', 'Base Completa'],
    ['SKUs en Quiebre (Stockout)', f'{skus_quiebre:,}', f'{skus_quiebre/total_skus*100:.1f}%', 'Riesgo Crítico'],
    ['SKUs con Recompra Sugerida', f'{skus_comprar:,}', f'{skus_comprar/total_skus*100:.1f}%', 'Orden de Compra Requerida'],
    ['Unidades Totales a Comprar', f'{unidades_comprar:,.0f} u', '-', 'Inversión Sugerida']
]

tabla_kpis = Table(datos_kpi, colWidths=[200, 100, 90, 150])
tabla_kpis.setStyle(TableStyle([
    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1f77b4')),
    ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
    ('FONTSIZE', (0,0), (-1,0), 10),
    ('ALIGN', (1,0), (-1,-1), 'CENTER'),
    ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8f9fa')),
    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cccccc')),
    ('TEXTCOLOR', (3,2), (3,2), colors.HexColor('#d62728')),
]))

story.append(tabla_kpis)
story.append(Spacer(1, 20))

# --- INCORPORACIÓN DE GRÁFICOS ---
print("🖼️ Insertando Gráficos Estadísticos...")

figura_bodega = "reports/figures/stock_por_bodega.png"
figura_quiebres = "reports/figures/top_quiebres_categoria.png"
figura_matriz = "reports/figures/matriz_riesgo_stock.png"

if os.path.exists(figura_bodega):
    story.append(Paragraph("1. Distribución Físico por Bodega", seccion_style))
    story.append(Image(figura_bodega, width=520, height=280))
    story.append(Spacer(1, 15))

if os.path.exists(figura_quiebres):
    story.append(PageBreak())
    story.append(Paragraph("2. Top Categorías con Mayor Quiebre", seccion_style))
    story.append(Image(figura_quiebres, width=520, height=280))
    story.append(Spacer(1, 15))

if os.path.exists(figura_matriz):
    story.append(Paragraph("3. Matriz de Riesgo: Disponible Hoy vs Stock Mínimo", seccion_style))
    story.append(Image(figura_matriz, width=520, height=310))

# 6. Compilamos el archivo PDF
doc.build(story)
print(f"\n🎉 ¡REPORTE PDF GENERADO CON ÉXITO!")
print(f"📄 Archivo generado: {ruta_pdf}")
