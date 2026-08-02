# 📊 Guía de Integración Power BI & Medidas DAX: Stock Proyectado Pesco

Esta guía detalla los pasos para cargar el dataset procesado por el pipeline de Python en **Power BI Desktop** y configurar el modelo dimensional de datos con medidas DAX de alto nivel.

---

## 🔌 1. Conexión de Datos (Paso a Paso)

1. Abre **Power BI Desktop**.
2. Ve a la pestaña **Inicio** $\rightarrow$ **Obtener datos** $\rightarrow$ **Texto/CSV**.
3. Selecciona la ruta del archivo procesado:
   `d:\informatica\Data-Science\stock_proyectado_pesco\data\processed\stock_proyectado.csv`
4. En la ventana emergente, asegura la siguiente configuración:
   - **Origen de archivo**: `65001: Unicode (UTF-8)`
   - **Detección de tipo de datos**: `Basado en las primeras 200 filas`
5. Haz clic en **Cargar**.

---

## 🧮 2. Tabla de Medidas DAX

Crea una nueva tabla de medidas llamada `_Medidas_Inventario` e incluye las siguientes expresiones:

### 🟢 KPIs de Volumen de Inventario
```dax
Total Stock Físico = SUM(stock_proyectado[Stock Total])
```
```dax
Disponible Hoy Total = SUM(stock_proyectado[Disponible Hoy])
```
```dax
Disponible Futuro Total = SUM(stock_proyectado[Disponible Futuro])
```

### 🔴 KPIs de Alerta y Quiebre
```dax
SKUs en Quiebre = 
CALCULATE(
    COUNTROWS(stock_proyectado),
    stock_proyectado[Estado_Stockout] = TRUE()
)
```
```dax
% SKUs en Quiebre = 
DIVIDE([SKUs en Quiebre], COUNTROWS(stock_proyectado), 0)
```
```dax
SKUs Bajo Mínimo = 
CALCULATE(
    COUNTROWS(stock_proyectado),
    stock_proyectado[Estado_Bajo_Minimo] = TRUE()
)
```

### 🔮 KPIs del Modelo ROP y Recompra
```dax
SKUs con Orden de Compra Sugerida = 
CALCULATE(
    COUNTROWS(stock_proyectado),
    stock_proyectado[Alerta_Recompra] = TRUE()
)
```
```dax
Total Unidades Sugeridas a Comprar = SUM(stock_proyectado[Sugerido_Comprar])
```

---

## 🎨 3. Visualizaciones Recomendadas para el Dashboard de Power BI

1. **Fila Superior (Tarjetas KPI / Cards)**:
   - `Total Stock Físico`
   - `SKUs en Quiebre` (Formato condicional Rojo)
   - `SKUs con Orden de Compra Sugerida` (Formato condicional Amarillo)
   - `Total Unidades Sugeridas a Comprar`
2. **Gráfico de Barras Horizontales**:
   - Eje Y: `Grupo Articulo`
   - Eje X: `[SKUs en Quiebre]`
3. **Gráfico de Matriz / Tabla Detallada**:
   - Columnas: `Codigo`, `Nombre`, `Grupo Articulo`, `Disponible Hoy`, `Punto_de_Reorden_Calculado`, `Sugerido_Comprar`.
   - Filtro Slicer por `Grupo Articulo` y `Alerta_Recompra`.
