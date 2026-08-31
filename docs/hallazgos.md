# Hallazgos — comparativa Reports API vs Data Kiosk

Corrido con credenciales de produccion de Acer MX (marketplace
`A1AM78C64UM0Y8`), rango de prueba **2026-08-17 -> 2026-08-23**.
Fecha de la corrida: 2026-08-26.

## 1. Acceso

- [x] Self-authorization completado, `.env` cargado
- [x] `check_auth.py` pasa — access token OK, Reports API responde 200
- [x] Rol Brand Analytics disponible: **si** — Data Kiosk acepto y ejecuto
      queries sin 403

## 2. Opcion A — Reports API

- Tiempo hasta `DONE`: **< 1 min** por reporte (`IN_QUEUE` -> `DONE` en un
  solo ciclo de polling de 30s).
- Formato: **JSON plano, sin comprimir**. Raiz con `reportSpecification`,
  un bloque `*Aggregate` (totales por dia) y un bloque `*ByAsin`.
- Filas devueltas: ventas **175** (25 ASINs) / inventario **413** (59 ASINs).
- Campos (sales, `salesByAsin[]`): `startDate`, `endDate`, `asin`,
  `customerReturns`, `shippedCogs`, `shippedRevenue`, `shippedUnits`.
- Campos (inventory, `inventoryByAsin[]`): 22 campos, incluyendo
  `sellableOnHandInventoryUnits`, `openPurchaseOrderUnits`,
  `sellThroughRate`, `netReceivedInventoryUnits`, `unhealthyInventoryUnits`.
- Moneda: **MXN** (confirma que el marketplace esta bien configurado).

### Problemas encontrados

1. **`reportOptions` incompletas.** Faltaba `sellingProgram`; es
   obligatorio junto con `reportPeriod` y `distributorView`. Sin el,
   `createReport` devuelve 400. Corregido en `spapi/reports.py`.
2. **No devuelve ningun identificador de producto propio** — solo ASIN.
   No hay `modelNumber` ni equivalente.
3. **Cobertura desigual entre reportes**: 34 ASINs estan en inventario pero
   no tienen fila en ventas. No asumir el mismo universo de ASINs.
4. Varios campos vienen `null` a nivel ASIN (`sellThroughRate`,
   `openPurchaseOrderUnits`). El loader debe tolerar nulos, no asumir 0.

## 3. Opcion B — Data Kiosk

- Tiempo hasta `DONE`: **~40-60s** (`IN_QUEUE` -> `IN_PROGRESS` -> `DONE`).
- Dominio: `analytics_vendorAnalytics_2024_09_30`, vista `sourcingView`.
- Filas: JSONL con **una linea por dia**, registros por ASIN anidados en
  `metrics[]`. Ventas 7 dias = 7 lineas / 69 registros / 25 ASINs.
  Ventas+inventario 1 dia = 1 linea / 186 registros / 172 ASINs.
- **Sell-out e inventario si salen en una sola query** — ambos viven en el
  mismo bloque `metrics` de `sourcingView`.

### Problemas encontrados

1. **La query original del proyecto era inventada.** Los campos
   `vendorSales` / `vendorInventory` no existen. El schema real usa
   `sourcingView` / `manufacturingView` con `aggregateBy` (no
   `aggregatedBy`). Reescrita contra el schema oficial
   (`amzn/selling-partner-api-models`, `analytics_vendorAnalytics_2024_09_30.graphql`).
2. **Un dominio versionado admite un solo campo de primer nivel.** No se
   pueden pedir `sourcingView` y `manufacturingView` juntos.
3. **Inventario diario exige `startDate == endDate`.** Con
   `aggregateBy: DAY`, un rango multi-dia con `productAvailability` falla
   como **FATAL en procesamiento, no como 400** — o sea, se pierde el
   tiempo de la query antes de enterarse. N dias de historia de inventario
   = N queries.
4. **La introspeccion GraphQL esta bloqueada** ("Query did not have a
   versioned domain field"), y adivinar nombres de campo cuesta una query
   por intento. Hay que trabajar contra el schema descargado.
5. `units` viene `null` en vez de 0 cuando no hay dato (129 de 186
   registros de inventario en la muestra de un dia).

## 4. Validacion cruzada

Las dos fuentes dan **exactamente los mismos numeros**, lo que da confianza
en cualquiera de las dos:

| Metrica | Reports API | Data Kiosk |
|---|---|---|
| Sell-out: registros con venta (7 dias) | 69 | 69 |
| Sell-out: ASINs con venta | 25 | 25 |
| Sell-out: unidades totales | 131 | 131 |
| Inventario 2026-08-23: unidades sellable on-hand | 4396 | 4396 |

## 5. Decision

**Opcion elegida: Data Kiosk (Opcion B).**

Motivos, en orden de peso:

1. **`modelNumber`.** Es la unica de las dos que devuelve un identificador
   de producto ademas del ASIN. Ataca directamente el punto abierto mas
   caro del proyecto (ASIN -> partnumber): resuelve ~46% de los SKUs de
   forma directa y el resto queda con `productTitle` y `brand` para
   completar el mapeo. El Reports API no ofrece nada de esto.
2. **Los numeros cuadran** con el Reports API, asi que no se sacrifica
   exactitud al cambiar de fuente.
3. **Direccion de Amazon**: Data Kiosk reemplaza progresivamente al
   Reports API. Construir sobre la Opcion A es construir sobre algo que se
   va a deprecar.
4. Un solo flujo cubre sell-out e inventario; el Reports API necesita dos
   reportes distintos.

Costo por corrida semanal: **2 queries** — una de sell-out sobre los 7 dias
(`--solo-ventas`) y una de inventario del dia de cierre. El limite de
`startDate == endDate` no duele porque el inventario que interesa es el
snapshot de cierre, no su historia diaria.

### Riesgos asumidos

- Lag de hasta ~34h: el rango debe cerrar al menos 3 dias atras
  (`DATA_LAG_DAYS`). Un cierre semanal debe correr con ese desfase.
- `modelNumber` no es un SKU limpio en todos los casos; hace falta una
  tabla de equivalencia para el resto. No es un bloqueo, es trabajo
  incremental.
- Rate limit de `createQuery` es bajo. Con 2 queries por corrida semanal no
  molesta, pero no se puede iterar dia por dia sin cuidado.
- Si Amazon cambia la version del dominio (`_2024_09_30`), la query hay que
  migrarla. Conviene fijar el schema descargado en el repo.

### Trabajo pendiente antes del loader definitivo

1. Resolver la tabla ASIN -> partnumber para el ~54% que `modelNumber` no
   cubre limpiamente (Catalog Items API o catalogo de Vendor Central).
2. Definir `customer_code` para el canal (ej. `AMAZON_MX`).
3. Escribir el aplanado `linea.metrics[]` -> filas
   `(customer_code, report_type, partnumber, units, date_id)`.
4. UPSERT con clave natural
   `(customer_code, report_type, partnumber, date_id)`, igual que Exel.
5. Mantener el Reports API como fallback/reconciliacion: es rapido, ya
   funciona, y sirve para auditar los numeros del Data Kiosk.
