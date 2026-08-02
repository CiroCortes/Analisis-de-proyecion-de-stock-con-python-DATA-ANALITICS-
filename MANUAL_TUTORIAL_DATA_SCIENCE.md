# 📘 Manual Tutorial & Ayuda Memoria: Sistema de Gestión de Stock Pesco S.A.

Este documento sirve como manual técnico de referencia, guía de arquitectura y tutorial de ayuda memoria para el mantenimiento del pipeline de **Data Science & Analytics para la Proyección de Stock Pañol (Pesco S.A.)**.

---

## 🏗️ Arquitectura del Proyecto

```text
stock_proyectado_pesco/
├── data_set.xlsx                   # Archivo original en Excel fuente (.xlsx)
├── data/
│   └── processed/                  # Datasets procesados por los módulos Python
│       ├── stock_procesado.csv     # Dataset limpio (Módulo 1)
│       └── stock_proyectado.csv    # Dataset enriquecido con modelo ROP (Módulo 4)
├── src/
│   ├── clean_data.py               # Módulo 1: ETL y Limpieza de datos
│   ├── eda_kpis.py                 # Módulo 2: Análisis Exploratorio y KPIs
│   ├── visualizations.py           # Módulo 3: Generación de Gráficos Ejecutivos
│   ├── stock_projection.py         # Módulo 4: Modelo de Proyección y Punto de Reorden (ROP)
│   └── generate_pdf.py             # Módulo 5: Generador automatizado de Reportes PDF
├── reports/
│   ├── figures/                    # Imágenes PNG de gráficos en alta resolución
│   └── Reporte_Ejecutivo_Inventario_Pesco.pdf  # PDF final autogenerado
├── powerbi/
│   └── GUIA_POWER_BI_MEDIDAS_DAX.md# Módulo 6: Guía de integración y fórmulas DAX
├── requirements.txt                # Dependencias de Python del proyecto
├── README.md                       # Documentación principal para despliegue en repositorio
└── MANUAL_TUTORIAL_DATA_SCIENCE.md # Este manual técnico de ayuda memoria
```

---

## ⚡ Secuencia de Ejecución (Pipeline Completo)

Para ejecutar el pipeline completo desde la consola (PowerShell / Terminal):

```powershell
# 1. Limpieza y Normalización de Datos
python src/clean_data.py

# 2. Diagnóstico de KPIs y Distribución por Bodegas
python src/eda_kpis.py

# 3. Generación de Gráficos Ejecutivos (PNG)
python src/visualizations.py

# 4. Proyección de Recompras y Algoritmo ROP
python src/stock_projection.py

# 5. Compilación del Reporte Ejecutivo PDF
python src/generate_pdf.py
```

---

## 📚 Módulos y Conceptos Clave (Ayuda Memoria)

### Módulo 1: ETL (`src/clean_data.py`)
- **`pd.read_excel()`**: Lectura del archivo `.xlsx` fuente.
- **Normalización**: Corrección de encodings (caracteres `Pañol`) y stripping de textos.
- **`.fillna()`**: Imputación de valores nulos por mediana de grupo (`groupby`).
- **Exportación**: `utf-8-sig` para compatibilidad nativa con Excel y Power BI.

### Módulo 2: KPIs (`src/eda_kpis.py`)
- **Filtros de Alerta**: Conteo de SKUs en Quiebre (`Disponible Hoy < 0`), Bajo Mínimo y Sobre-Stock.
- **`.groupby()` + `.sum()`**: Sumatoria de inventario físico en las 9 sucursales.

### Módulo 3: Visualizaciones (`src/visualizations.py`)
- **Estilo Corporativo**: `sns.set_theme(style="whitegrid")`.
- **Gráficos de Barras Horizontales**: `ax.barh()` para visualizar bodegas y categorías.
- **Matriz de Riesgo**: `sns.scatterplot()` con áreas de sombreado (`ax.axhspan`) para señalar zonas de quiebre.

### Módulo 4: Algoritmo ROP (`src/stock_projection.py`)
- **Punto de Reorden**: $\text{ROP} = (\text{Demanda Diaria} \times \text{Lead Time}) + \text{Stock de Seguridad}$.
- **Stock de Seguridad**: $\text{Safety Stock} = 1.65 \times \text{Demanda Diaria} \times \sqrt{\text{Lead Time}}$.
- **Segmentación**: Clasificación de SKUs inactivos (Demanda = 0.0) para evitar recompras innecesarias.

### Módulo 5: Reporte PDF (`src/generate_pdf.py`)
- **ReportLab**: Uso de `SimpleDocTemplate`, `Paragraph`, `Table`, `Image` y `doc.build(story)`.
