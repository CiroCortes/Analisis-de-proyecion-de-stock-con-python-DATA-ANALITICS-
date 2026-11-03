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
├── static/
│   ├── css/tailwind.css            # Tailwind compilado (se versiona)
│   └── vendor/                     # FontAwesome y Chart.js locales (se versionan)
├── tailwind/                       # Fuente de Tailwind y script de librerías (ver "Frontend y producción")
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

---

## 🖥️ Frontend y producción (para quien despliega)

La red de Pesco bloquea o no resuelve CDN externos (`cdn.tailwindcss.com` dejó de responder el 28-oct-2026).
Por eso **el sitio no carga nada desde internet**: todo el CSS, los íconos y los gráficos se sirven desde
`static/`, con versiones fijas. No hace falta Node ni acceso a internet para correr el sistema.

| Recurso | Archivo servido | Cómo se genera |
|---|---|---|
| Tailwind CSS 3.4.17 (colores Pesco) | `static/css/tailwind.css` | Compilado desde `tailwind/input.css` y `tailwind/tailwind.config.js` |
| FontAwesome 6.5.1 (CSS y fuentes) | `static/vendor/fontawesome/` | `tailwind/download_vendor.ps1` |
| Chart.js 4.4.0 | `static/vendor/chartjs/chart.umd.min.js` | `tailwind/download_vendor.ps1` |
| Estilos propios | `static/css/custom.css` | A mano |

Todos estos archivos **se versionan en git**: el despliegue usa lo que está en el repositorio.

### Regla para desarrolladores: recompilar Tailwind

Tailwind solo incluye en `tailwind.css` las clases que encuentra en las plantillas (`templates/**/*.html`)
y en el código Python. **Si se usa una clase nueva y no se recompila, la clase no existe y no hay ningún
error: simplemente no se aplica.** Después de tocar estilos, desde la raíz del proyecto (requiere Node e
internet, solo en el equipo de desarrollo):

    npx -y tailwindcss@3.4.17 -c tailwind/tailwind.config.js -i tailwind/input.css -o static/css/tailwind.css --minify

y subir el `tailwind.css` resultante junto con el cambio. Para actualizar FontAwesome o Chart.js, cambiar la
versión en `tailwind/download_vendor.ps1`, correrlo y subir `static/vendor/`. Nunca volver a enlazar un CDN.

No usar el formateo automático de HTML del editor en las plantillas: no entiende la sintaxis de Django,
parte las etiquetas `{{ ... }}` en varias líneas y quita espacios en `{% if a == b %}`, y la página se rompe.

### Despliegue en producción (AWS)

1. **Variables de entorno** (leídas en `core/settings.py`; sin ellas el sistema queda en modo desarrollo):

   | Variable | Producción | Por defecto |
   |---|---|---|
   | `DJANGO_DEBUG` | `0` | `1` |
   | `DJANGO_SECRET_KEY` | clave larga y aleatoria, fuera del repositorio | clave de desarrollo |
   | `DJANGO_ALLOWED_HOSTS` | dominio(s) del servidor, separados por coma | `*` |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://<dominio>` si hay HTTPS o un balanceador delante | vacío |

2. **Archivos estáticos.** Con `DJANGO_DEBUG=0`, Django **deja de servir** `/static/`; si nadie lo sirve, el
   sitio queda sin estilos, sin íconos y sin gráficos. En cada despliegue:

       python manage.py collectstatic --noinput

   Eso copia todo a `staticfiles/` (`STATIC_ROOT`). Luego, una de dos:
   - el servidor web (nginx, IIS o Apache) publica `staticfiles/` en la URL `/static/`; o
   - se agrega [WhiteNoise](https://whitenoise.readthedocs.io/) (`pip install whitenoise` y
     `whitenoise.middleware.WhiteNoiseMiddleware` después de `SecurityMiddleware`), y Django sirve los
     estáticos sin configurar el servidor web.

3. **Base de datos y migraciones:** `python manage.py migrate` en cada despliegue. Hoy la base es
   **SQLite** (`db.sqlite3`, ~180 MB): en el servidor debe estar en un disco persistente (no en el
   contenedor ni en una instancia efímera), con respaldo, y con un solo proceso escribiendo a la vez. Si se
   necesitan varios procesos o instancias, pasar a PostgreSQL (RDS) cambiando `DATABASES` en `core/settings.py`.

4. **Comprobación rápida:** con `DJANGO_DEBUG=0`, abrir el sitio con las herramientas del navegador
   (pestaña Red): ninguna petición debe ir a un dominio externo y ningún archivo de `/static/` debe dar 404.

---

## 📈 Resultados Destacados del Diagnóstico

- **Total SKUs Auditados**: 20.297 SKUs.
- **Stock Físico Almacenado**: 1.330.185 unidades distribuidas en 9 sucursales/bodegas.
- **Segmentación de SKUs**: 50,5% SKUs inactivos sin movimiento / 42,2% SKUs activos con reorden sugerido.
- **Reporte PDF Automatizado**: Disponible en `reports/Reporte_Ejecutivo_Inventario_Pesco.pdf`.
