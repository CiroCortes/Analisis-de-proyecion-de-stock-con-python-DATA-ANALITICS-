# 📦 Sistema de Análisis & Proyección de Stock Pesco S.A.

Pipeline automatizado de **Data Science, Analytics & Business Intelligence** para la auditoría, optimización de inventarios, cálculo de **Punto de Reorden (ROP)**, generación de **Reportes PDF Ejecutivos** y alimentación de tableros en **Power BI** para Pesco S.A.

---

## 🚀 Arquitectura y Estructura del Proyecto

```text
stock_proyectado_pesco/
├── data_set.xlsx                   # Archivo Excel fuente con la proyección de stock
├── data/
│   └── processed/                  # Datasets procesados por el pipeline
│       ├── stock_procesado.csv     # Dataset limpio y auditado (Módulo 1)
│       └── stock_proyectado.csv    # Dataset enriquecido con modelo ROP (Módulo 4)
├── src/
│   ├── clean_data.py               # Módulo 1: ETL, limpieza y encodings
│   ├── eda_kpis.py                 # Módulo 2: Análisis exploratorio y KPIs
│   ├── visualizations.py           # Módulo 3: Generación de gráficos ejecutivos (PNG)
│   ├── stock_projection.py         # Módulo 4: Algoritmo de Reorden y Sugerido de Compra
│   └── generate_pdf.py             # Módulo 5: Motor de reportes automatizados en PDF
├── reports/
│   ├── figures/                    # Gráficos en alta resolución (300 DPI)
│   │   ├── stock_por_bodega.png
│   │   ├── top_quiebres_categoria.png
│   │   └── matriz_riesgo_stock.png
│   └── Reporte_Ejecutivo_Inventario_Pesco.pdf  # Informe PDF generado
├── powerbi/
│   └── GUIA_POWER_BI_MEDIDAS_DAX.md# Guía de conexión y catálogo de medidas DAX
├── requirements.txt                # Dependencias de Python necesarias
├── MANUAL_TUTORIAL_DATA_SCIENCE.md # Manual técnico y ayuda memoria
└── README.md                       # Este archivo
```

---

## 🛠️ Instalación en el Computador de la Empresa

### 1. Clonar el repositorio y navegar a la carpeta
```bash
git clone <URL_DE_TU_REPOSISITORIO>
cd stock_proyectado_pesco
```

### 2. Instalar dependencias requeridas
```bash
pip install -r requirements.txt
```

---

## ⚡ Ejecución del Pipeline (Paso a Paso)

Ejecuta los módulos en orden desde tu terminal o PowerShell:

```powershell
# Paso 1: Limpieza de datos y tratamiento de encodings
python src/clean_data.py

# Paso 2: Cálculo de KPIs y distribución por bodegas
python src/eda_kpis.py

# Paso 3: Generación de visualizaciones ejecutivas
python src/visualizations.py

# Paso 4: Algoritmo ROP y sugerencia de compra segmentada
python src/stock_projection.py

# Paso 5: Compilación automatizada del informe ejecutivo en PDF
python src/generate_pdf.py
```

---

## 📊 Integración con Power BI Desktop

1. Abre **Power BI Desktop**.
2. Haz clic en **Obtener Datos** $\rightarrow$ **Texto/CSV**.
3. Selecciona el archivo enriquecido: `data/processed/stock_proyectado.csv`.
4. Asegura la codificación `65001: Unicode (UTF-8)`.
5. Revisa la guía de medidas DAX en [powerbi/GUIA_POWER_BI_MEDIDAS_DAX.md](powerbi/GUIA_POWER_BI_MEDIDAS_DAX.md) para construir tus tarjetas y tableros.

---

## 📈 Resultados Destacados del Diagnóstico

- **Total SKUs Auditados**: 20.297 SKUs.
- **Stock Físico Almacenado**: 1.330.185 unidades distribuidas en 9 sucursales/bodegas.
- **Segmentación de SKUs**: 50,5% SKUs inactivos sin movimiento / 42,2% SKUs activos con reorden sugerido.
- **Reporte PDF Automatizado**: Disponible en `reports/Reporte_Ejecutivo_Inventario_Pesco.pdf`.
