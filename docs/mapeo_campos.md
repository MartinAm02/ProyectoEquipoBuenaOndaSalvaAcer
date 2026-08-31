# Mapeo de campos SP-API -> columnas del ACER Report Loader

Columnas destino (las mismas de `so_wk_XX_2026.csv`):
`customer_code, report_type, partnumber, units, date_id`

## Opcion A — Reports API

### GET_VENDOR_SALES_REPORT

Verificado contra datos reales (Acer MX, 2026-08-17 -> 2026-08-23):
175 filas en `salesByAsin`, 25 ASINs, moneda MXN.

Raiz del JSON: `reportSpecification`, `salesAggregate` (totales por dia),
`salesByAsin` (una fila por ASIN y dia).

| Columna destino | Campo del reporte | Nota |
|---|---|---|
| `customer_code` | — | constante del canal (ej. `AMAZON_MX`), no viene en el payload |
| `report_type` | — | constante `SELL_OUT` |
| `partnumber` | `salesByAsin[].asin` | requiere equivalencia ASIN -> partnumber (ver abajo) |
| `units` | `salesByAsin[].shippedUnits` | sell-out real |
| `date_id` | `salesByAsin[].startDate` | con `reportPeriod: DAY`, `startDate == endDate` |

Campos reales de `salesByAsin[]` (los 7, ninguno nulo en la muestra):
`startDate`, `endDate`, `asin`, `customerReturns`, `shippedCogs`,
`shippedRevenue`, `shippedUnits`. Los montos son objetos
`{amount, currencyCode}`.

> Correccion: con `distributorView: SOURCING` **no** existen `orderedUnits`
> ni `orderedRevenue` — esos campos son de la vista MANUFACTURING. Solo hay
> `shippedUnits`, que es justamente el sell-out que necesitamos.

`reportOptions` obligatorias (las tres): `reportPeriod`, `distributorView`,
`sellingProgram`. Omitir `sellingProgram` hace fallar el `createReport`.

### GET_VENDOR_INVENTORY_REPORT

Verificado: 413 filas en `inventoryByAsin`, 59 ASINs, mismo rango.

| Columna destino | Campo del reporte | Nota |
|---|---|---|
| `customer_code` | — | constante del canal |
| `report_type` | — | constante `INVENTORY` |
| `partnumber` | `inventoryByAsin[].asin` | mismo mapeo ASIN -> partnumber |
| `units` | `inventoryByAsin[].sellableOnHandInventoryUnits` | stock disponible |
| `date_id` | `inventoryByAsin[].startDate` | snapshot diario |

Otros utiles: `openPurchaseOrderUnits`, `sellThroughRate`,
`unsellableOnHandInventoryUnits`, `netReceivedInventoryUnits`,
`aged90PlusDaysSellableInventoryUnits`, `unhealthyInventoryUnits`.

> Ojo: varios campos vienen `null` a nivel ASIN (`sellThroughRate`,
> `openPurchaseOrderUnits`, `sourceableProductOutOfStockRate`). El loader
> debe tolerar nulos, no asumir 0.

> Cobertura distinta entre reportes: 34 ASINs aparecen en inventario pero
> no tienen fila en ventas. No se puede hacer un join interno entre ambos
> asumiendo el mismo universo de ASINs.

## Opcion B — Data Kiosk (Cross-Domain Vendor Analytics)

Dominio `analytics_vendorAnalytics_2024_09_30`, vista `sourcingView`
(equivale a `distributorView: SOURCING` del Reports API). Verificado con
datos reales del mismo rango.

### Forma real del JSONL

No es una fila por ASIN. Es **una linea por bucket de fecha**, con los
registros por ASIN anidados:

```json
{"startDate":"2026-08-17","endDate":"2026-08-17","marketplaceId":"A1AM78C64UM0Y8",
 "metrics":[{"groupByKey":{"asin":"B0FDLW5T5H","modelNumber":"NX.D4CAL.002","brand":"acer"},
             "metrics":{"shippedOrders":{...},"productAvailability":{...}}}]}
```

El loader tiene que aplanar `linea.metrics[]`, no leer linea por registro.

### Mapeo

| Columna destino | Ruta en el JSONL |
|---|---|
| `customer_code` | constante del canal |
| `report_type` | constante `SELL_OUT` / `INVENTORY` |
| `partnumber` | `metrics[].groupByKey.modelNumber` (o `.asin` de fallback) |
| `units` (sell-out) | `metrics[].metrics.shippedOrders.shippedUnitsWithRevenue.units` |
| `units` (inventario) | `metrics[].metrics.productAvailability.sellableOnHandInventory.units` |
| `date_id` | `startDate` de la linea contenedora |

Otros: `averageSellingPrice`, `sellThroughRate`, `sellableInTransitInventory`,
`unsellableOnHandInventory.units`, y en `groupByKey` tambien `brand`,
`brandCode`, `productTitle`, `upc`, `ean`, `vendorCode`, `parentAsin`.

### Restricciones verificadas

1. **Un solo campo de primer nivel por dominio.** `sourcingView` y
   `manufacturingView` no caben en la misma query
   ("Versioned domain cannot select multiple query fields"). Irrelevante
   en la practica: sell-out e inventario viven ambos dentro de `metrics`
   de una misma vista, asi que **si** se obtienen en una sola llamada.
2. **Inventario diario exige `startDate == endDate`.** Con
   `aggregateBy: DAY`, pedir `productAvailability` sobre un rango falla en
   procesamiento (FATAL, no 400): *"The same start and end dates must be
   requested for Daily Inventory metrics"*. Un rango de N dias con
   inventario = N queries. Codificado como guardia en
   `query_sales_e_inventory()`.
3. `units` viene `null` (no 0) cuando no hay dato. En la muestra de un dia,
   129 de 186 registros tenian `sellableOnHandInventory.units = null`.

### Validacion cruzada contra la Opcion A

Mismo rango, mismos numeros — las dos fuentes concuerdan:

| Metrica | Reports API | Data Kiosk |
|---|---|---|
| Sell-out: registros con venta | 69 | 69 |
| Sell-out: ASINs con venta | 25 | 25 |
| Sell-out: unidades totales (7 dias) | 131 | 131 |
| Inventario 2026-08-23: unidades | 4396 | 4396 |

## Punto abierto: ASIN vs partnumber (parcialmente resuelto)

**Data Kiosk devuelve `modelNumber` en `groupByKey`; el Reports API no
devuelve nada equivalente.** Eso lo vuelve el candidato natural para
`partnumber` y es la ventaja mas concreta de la Opcion B.

Cobertura medida:

- Query de ventas (69 registros): `modelNumber` poblado en **69/69**.
- Query de inventario (186 registros): poblado en **158/186**.
- Del total, solo ~46% calza el formato de SKU Acer `NX.XXXXX.XXX`
  (ej. `NX.D4CAL.002`, `NH.D23AL.001`, `UM.QX1AA.S01`).

El resto trae nombres comerciales de modelo, no el SKU: `AMR800 Black`,
`PM161QT bmiuuux`, `A315-58-34S8`, `20CH1Q bi`. Es decir, `modelNumber`
resuelve aproximadamente la mitad de los casos de forma directa y deja la
otra mitad para una tabla de equivalencia.

Plan sugerido: usar `modelNumber` cuando calce el patron de SKU, y para el
resto mantener una tabla ASIN -> partnumber alimentada del catalogo de
Vendor Central (o via Catalog Items API, `/catalog/2022-04-01/items`).
Conviene persistir tambien `asin` y `productTitle` para poder auditar y
completar el mapeo incrementalmente.

## Idempotencia

La clave natural para el UPSERT es
`(customer_code, report_type, partnumber, date_id)`, igual que en el
canal Exel. Ambas fuentes son re-consultables sobre el mismo rango de
fechas, asi que reprocesar un rango es seguro siempre que se respete esa
clave.
