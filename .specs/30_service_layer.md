# SPEC-30: Conexión al SAP B1 Service Layer (solo lectura)

Fecha: 29-oct-2026. Origen: el Datalake tiene movimientos duplicados, meses faltantes y OC que no
aparecen (bitácora local); cada consulta se exporta a mano y en días distintos. TI de Pesco entregó
acceso al Service Layer (SL) con una base de pruebas.
Código: `apps/data_ingestion/service_layer.py`, `manage.py sl_probar`. Tests: `tests/test_service_layer.py`.

---

## 1. Condiciones de TI (obligatorias)

1. **Solo desde la red de Pesco.** El SL responde solo a las IP nateadas al Datacenter (casa matriz).
2. **Nunca escribir en SAP por SQL** (INSERT, UPDATE, DELETE): se pierde el soporte de SAP y puede
   haber multa. Las únicas vías soportadas son SL, DI API y UI API. **La plataforma no escribe en
   SAP por ninguna vía** (decisión del 28-oct): las compras salen por Excel.
3. **No sobrecargar el servidor**: se cae con muchas consultas. Slim4 corre unas 3 veces al día.
4. **Pruebas en la base `X_CHILE_PRUEBAS`.** IP, usuario y clave solo en `.env` (nunca en el
   repositorio, que es público). La clave no se escribe en código ni en documentos.

## 2. Cómo lo hace cumplir el código

| Regla | Implementación |
|---|---|
| Solo lectura | Un único punto de salida (`_enviar`). Solo GET, más POST a `Login` y `Logout`. Cualquier otro método o ruta lanza `EscrituraProhibida` **antes** de salir a la red (test por método) |
| Base de pruebas | `SAP_SL_COMPANY` debe estar en `SAP_SL_BASES_PRUEBA` (por defecto `X_CHILE_PRUEBAS`). Producción exige `SAP_SL_PERMITIR_PRODUCCION=1`, acordado con TI |
| Red de Pesco | Antes del Login abre un socket al puerto (5 s). Si no responde: `SinConexion` con el motivo, sin reintentar |
| Clave protegida | Solo `https://`. Se verifica el certificado: TI entrega el certificado (`SAP_SL_CA_BUNDLE`). Desactivar la verificación existe pero no se recomienda |
| Carga | Una sesión por corrida y Logout siempre (también si hay error). Peticiones en secuencia con pausa (0,5 s). Páginas de 100 filas (`Prefer: odata.maxpagesize`). `$select` obligatorio; `$filter` en el servidor. Presupuesto de 300 peticiones por corrida |
| Servidor cargado | Timeout de 30 s. Corta la corrida (`CorteDeSeguridad`) tras 3 respuestas de más de 15 s o 3 errores seguidos. Los datos anteriores siguen vigentes |
| Trazabilidad | `Estadisticas`: peticiones, filas, segundos, lentas, errores y el detalle de cada petición |

Todos los límites se ajustan en `.env` (ver `.env.example`).

## 3. Prueba de conexión

`python manage.py sl_probar`, desde la red de Pesco, contra `X_CHILE_PRUEBAS`: Login, 5 bodegas,
3 artículos, conteo de OC abiertas y Logout (presupuesto de 5 peticiones). Muestra el tiempo de cada
petición. Sin clave o fuera de la red se detiene antes de enviar nada.

## 4. Plan

1. **Fase 0 (este cambio)**: cliente seguro y prueba de conexión.
2. **Fase 1**: foto diaria (stock por bodega, OC, SC, PC y OF abiertos) en la base de pruebas, en
   una sola tanda (sin desfase entre consultas). Contrastar 30 artículos con SAP.
3. **Fase 2**: consumo. OINM no es un objeto estándar del SL: (a) consultas fijas creadas por TI
   y solo leídas por la plataforma, o (b) armarlo desde los documentos (entregas, devoluciones,
   facturas, NC, salidas). Carga inicial de noche, mes a mes; después solo lo nuevo.
4. **Fase 3**: 2 o 3 corridas programadas al día en horarios acordados con TI, con el control de
   calidad (no se publica si un mes cerrado cambia o algo no cuadra).

## 5. Preguntas abiertas para TI

1. ¿El usuario del SL es de solo lectura? ¿Qué licencia consume cada sesión?
2. ¿Horarios y frecuencia permitidos? ¿Máximo de peticiones por corrida?
3. ¿Certificado del servidor para verificar la conexión?
4. ¿Pueden crear consultas fijas para OINM (opción a de la fase 2)?
5. ¿Slim4 lee por SL o directo de la base?
6. ¿En qué equipo de la red de Pesco correría la plataforma en producción?
