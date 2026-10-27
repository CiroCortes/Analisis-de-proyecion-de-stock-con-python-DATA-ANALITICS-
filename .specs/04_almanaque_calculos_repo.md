> **OBSOLETO (27-oct-2026).** Reglas de clasificación del motor anterior (R = 2 meses, E por
> servicio de pañol, ABC por frecuencia). Lo reemplazan SPEC-09 (clasificación) y SPEC-10
> (cálculo). Se conserva como referencia histórica.

# ALMANAQUE Y MANUAL DE CÁLCULOS S&OP - PESCO S.A.
**Guía Oficial en Lenguaje Claro y Práctico para Abastecimiento y Operaciones**

---

## 1. INTRODUCCIÓN: ¿CÓMO CONVIVEN LAS CLASIFICACIONES?

En el sistema conviven 2 clasificaciones complementarias para cada material (SKU):

1. **Clasificación Slim4 (Ya existente y se mantiene intacta)**:
   - **Segmento**: Runners (alta frecuencia), Repeaters (frecuencia media), Strangers (esporádicos).
   - **Matriz ABC-XYZ**: Valorización económica vs Variabilidad de la demanda.
   - **Política de Stock**: Stock / No Stock.

2. **Clasificación REPO (Nueva - Nomenclatura Operativa PESCO)**:
   - Se calcula automáticamente cada mes de forma dinámica según el comportamiento real del material.
   - Define qué tipo de regla de compra o traslado aplica para cada producto.

---

## 2. DICCIONARIO DE CLASIFICACIÓN REPO (¿QUÉ SIGNIFICA CADA LETRA?)

### [ R ] = Rotación (Equivalente en planilla: VB)
* **¿Qué es?**: Material de consumo frecuente. Se ha movido en **2 o más meses** durante el último año (12 meses).
* **¿Cómo se abastece?**: Se calcula un **Punto de Reorden (ROP)** estadístico. Cuando el stock proyectado cae por debajo del ROP, el sistema recomienda reponer.

### [ E ] = Estratégico / Crítico (Equivalente en planilla: V1)
* **¿Qué es?**: Material vital para la continuidad operativa (declarado como "Parte Crítica = X").
* **¿Cómo se abastece?**: No depende solo de si rota mucho o poco. El área de operaciones o mantenimiento le fija un **Stock Mínimo Obligatorio**. El sistema siempre vigilará que nunca estemos por debajo de ese mínimo.

### [ P ] = A Pedido (Equivalente en planilla: PD)
* **¿Qué es?**: Material que no tiene consumo habitual ni es crítico de stock permanente, pero que fue solicitado para un trabajo puntual con una **Orden de Fabricación (OF)** o un **Pedido de Cliente (PC)**.
* **¿Cómo se abastece?**: Se sugiere comprar o trasladar **exactamente la cantidad que pide la orden**, ni una unidad más ni una menos.

### [ O ] = Obsoleto / Sin Movimiento (Equivalente en planilla: ND)
* **¿Qué es?**: Material que lleva **más de 1 año (12 meses) sin ningún movimiento**, no está marcado como Crítico (E) ni tiene pedidos pendientes (P).
* **¿Cómo se abastece?**: **No se sugiere compra automática**. Si llega a entrar un requerimiento manual, el sistema lo trata como pedido pero levanta una **Alerta de Obsolescencia** para no acumular stock muerto.

---

## 3. CÁLCULO DEL PUNTO DE REORDEN (ROP) EXPLICADO EN PALABRAS SIMPLES

El archivo de parámetros calcula el Punto de Reorden (ROP) sumando dos componentes:
$$\text{Punto de Reorden (ROP)} = \text{Consumo durante el tiempo de entrega} + \text{Colchón de Seguridad}$$

En detalle:

### Paso 1: Consumo Promedio Mensual
* Se suman las salidas de los últimos 12 meses y se divide por 12.
* *Ejemplo*: Si en el año salieron 120 unidades, el consumo promedio es **10 unidades al mes**.

### Paso 2: Tiempo de Entrega del Proveedor (Lead Time)
* Se toma el tiempo que demora el proveedor en días y se pasa a meses (días / 30).
* *Ejemplo*: Si el proveedor demora 60 días, el tiempo de entrega es **2 meses**.

### Paso 3: Stock Mínimo (Consumo durante la espera)
* Es lo que vamos a gastar mientras esperamos que llegue el pedido, más una semana extra (0.25 meses) por trámites administrativos y recepción.
* **Fórmula simple**: (Tiempo de entrega en meses + 0.25) × Consumo Promedio Mensual
* *Ejemplo*: (2 meses + 0.25) × 10 unidades = **22.5 unidades (aprox. 23 unidades)**.

### Paso 4: Stock de Seguridad (El colchón para imprevistos)
* Protege si el proveedor se atrasa o si los clientes compran más de lo normal en un mes.
* Depende de la **variabilidad de los consumos (desviación)** y de la **importancia del repuesto**:
  * Si es **Crítico (E)**: Se exige un nivel de protección del **95%** (Factor 1.645).
  * Si es **Normal (R)**: Se exige un nivel de protección del **90%** (Factor 1.28).
* *Ejemplo*: Si el cálculo de seguridad da **8 unidades**, ese es nuestro colchón intocable.

### Paso 5: Punto de Reorden Final (ROP)
* **ROP = Stock Mínimo + Stock de Seguridad**
* *Ejemplo*: 23 unidades + 8 unidades = **31 unidades**.
* *¿Qué significa?*: En el momento en que nuestro stock disponible baje a **31 unidades**, el sistema levanta la alerta para abastecer.

### Paso 6: Stock Máximo
* Es el límite superior para no sobrestockear la bodega. Equivale al ROP más 3 meses de consumo habitual.
* *Ejemplo*: 31 unidades + (3 meses × 10 unidades) = **61 unidades máximas**.

---

## 4. CÁLCULO DE LA DISPONIBILIDAD Y QUIEBRE POR BODEGA

Para cada bodega se analiza su foto actual y futura:

* **Disponible Futuro**:
  $$\text{Stock Físico Hoy} + \text{Solicitudes de Compra} + \text{Órdenes en Camino} - \text{Compromisos de Clientes} - \text{Compromisos de Fabricación}$$

* **Nivel de Urgencia**:
  * **CRÍTICO**: El Disponible Futuro es cero o negativo (hay clientes o talleres esperando y no alcanza el stock físico + camino).
  * **MEDIO**: El Disponible Futuro es positivo, pero está por debajo del Punto de Reorden (ROP). Hay que pedir para no quebrar pronto.
  * **NORMAL**: El Disponible Futuro está por encima del ROP. Stock saludable.

---

## 5. LÓGICA DE DECISIÓN: TRASLADO INTERNO VS COMPRA A PROVEEDOR

Para evitar comprar stock innecesario a proveedores cuando ya existe mercadería en la empresa:

```
¿La bodega sucursal necesita material? (Ejemplo: Antofagasta necesita 30 unidades)
       │
       ▼
¿Hay stock libre en las bodegas centrales de Santiago (013-*) sin compromisos y por sobre su seguridad?
       │
       ├─► SÍ (Ej: Santiago tiene 50 unidades libres)
       │     └─► RECOMENDACIÓN: TRASPASO INTERNO (Mover 30 unidades de Santiago a Antofagasta)
       │         Compra a proveedor = 0 unidades.
       │
       ├─► PARCIAL (Ej: Santiago solo tiene 10 unidades libres)
       │     └─► RECOMENDACIÓN MIXTA:
       │         • Traspaso Interno = 10 unidades.
       │         • Compra a Proveedor = 20 unidades restantes.
       │
       └─► NO (Santiago no tiene stock libre)
             └─► RECOMENDACIÓN: COMPRA A PROVEEDOR por 30 unidades.
```

---

## 6. MAPA DE REPORTES Y GRÁFICOS GERENCIALES (SOLICITUD GISELLA)

1. **Gráfico 1 (% Disponibilidad Histórica)**: Evolución mensual del nivel de servicio por sucursal.
2. **Gráfico 2 (Monto Total de Inventario $)**: Evolución mensual del valor del inventario por sucursal (colocado al lado del Gráfico 1 para comparar tendencias).
3. **Módulo 3 (Listado de SKUs en Quiebre)**: Tabla ordenada de mayor a menor según los **días en quiebre** acumulados.
4. **Gráfico 4 (Evolución de Compras a Pedido)**: Montos mensuales de compras tipo 'P' a lo largo del tiempo.
5. **Módulo 5 (Ranking de Materiales a Pedido)**: Listado ordenado del SKU más caro al más barato con inventario a pedido.
6. **Módulo 6 (Ranking por Solicitante / Responsable)**: Nombre y apellido ordenado por el monto total de inventario a pedido generado.
