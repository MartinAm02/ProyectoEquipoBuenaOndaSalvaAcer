# Como funciona la SP-API en este proyecto

Referencia tecnica completa: autenticacion, endpoints, variables de
entorno, parametros de cada operacion y forma exacta de lo que se baja en
crudo. Todo lo marcado como **verificado** se comprobo contra la cuenta de
produccion de Acer MX (marketplace `A1AM78C64UM0Y8`) el 2026-08-26.

---

## 1. Panorama

La SP-API es una API REST sobre HTTPS. Las tres piezas:

```
   .env  --->  LWA (api.amazon.com)  --->  access token (1 h)
                                                |
                                                v
                                sellingpartnerapi-na.amazon.com
                                                |
                   +----------------------------+----------------------------+
                   v                                                         v
        Reports API (Opcion A)                              Data Kiosk (Opcion B)
        /reports/2021-06-30                                 /dataKiosk/2023-11-15
                   |                                                         |
    createReport -> polling -> getReportDocument     createQuery -> polling -> getDocument
                   |                                                         |
                   v                                                         v
        JSON plano (gzip) en out/                       JSONL (sin comprimir) en out/
```

Ambos caminos son **asincronos**: se solicita el trabajo, se hace polling
del estado, y recien al terminar se descarga un documento desde una URL
prefirmada de S3.

> **Nota importante:** SP-API **ya no exige firma AWS SigV4** para llamadas
> normales. Basta el header `x-amz-access-token`. Documentacion o librerias
> viejas que hablan de firmar con `AWS4-HMAC-SHA256` y roles de IAM estan
> desactualizadas. Este proyecto no firma nada.

---

## 2. Autenticacion (LWA - Login with Amazon)

### 2.1 El flujo

Amazon separa dos cosas:

| | Que es | Como se obtiene | Caduca |
|---|---|---|---|
| **Client ID / Secret** | Identifican la *aplicacion* | Registro de la app en Solution Provider Portal | Rotar cada 12 meses |
| **Refresh Token** | Autoriza a la app sobre *tu cuenta* | Self-authorization en Vendor Central -> Central de Desarrolladores -> Autorizar | No caduca (se revoca) |
| **Access Token** | Credencial de uso | Se pide con el refresh token | **1 hora** |

El refresh token es de larga vida y se guarda en el `.env`. El access token
se pide en cada arranque y se cachea en memoria.

### 2.2 La llamada

`POST https://api.amazon.com/auth/o2/token`
Content-Type: `application/x-www-form-urlencoded`

| Parametro | Valor |
|---|---|
| `grant_type` | `refresh_token` |
| `refresh_token` | el del `.env` |
| `client_id` | el del `.env` |
| `client_secret` | el del `.env` |

Respuesta (200):

```json
{
  "access_token": "Atza|IwEBI...",
  "refresh_token": "Atzr|IwEBI...",
  "token_type": "bearer",
  "expires_in": 3600
}
```

Implementado en [`spapi/auth.py`](../spapi/auth.py). La clase `LwaAuth`
cachea el token y lo renueva sola cuando faltan menos de **60 segundos**
para que expire (margen para que no caduque en pleno request).

### 2.3 Uso del access token

En cada llamada a SP-API:

```
x-amz-access-token: Atza|IwEBI...
content-type: application/json
```

**Excepcion:** la descarga del documento final va a una URL prefirmada de
S3 y **no debe llevar el header** - el token ahi sobra y puede hacer fallar
la firma. Por eso `SpApiClient.download()` usa la sesion pelada.

### 2.4 Diagnostico de credenciales

El error de LWA distingue que esta mal:

| Respuesta | Significa |
|---|---|
| `401 invalid_client` | `client_id` o `client_secret` incorrectos |
| `400 invalid_grant` | refresh token invalido, revocado, o de otra app |
| `400 invalid_scope` | credenciales **correctas**, pero la app no tiene ese scope |

> Truco util: un `POST` con `grant_type=client_credentials` y un scope
> cualquiera valida el par ID/secret **sin necesitar el refresh token**. Si
> responde `invalid_scope` en vez de `invalid_client`, las credenciales de
> la app son buenas. Asi se confirmo que faltaba unicamente el refresh
> token. **Verificado.**

---

## 3. Endpoints y regiones

Mexico pertenece a la region **NA** (Norteamerica), junto con US, CA y BR.

| Region | Endpoint |
|---|---|
| **NA** (US, CA, MX, BR) | `https://sellingpartnerapi-na.amazon.com` |
| EU | `https://sellingpartnerapi-eu.amazon.com` |
| FE (Lejano Oriente) | `https://sellingpartnerapi-fe.amazon.com` |

El endpoint de LWA es global: `https://api.amazon.com/auth/o2/token`.

**Marketplace ID de Mexico: `A1AM78C64UM0Y8`.** El endpoint define la
region; el `marketplaceId` define el pais concreto dentro de esa region.
Los dos tienen que ser coherentes o la API devuelve datos vacios sin error
explicito.

---

## 4. El archivo `.env`

Se carga en [`config/settings.py`](../config/settings.py) con un parser
propio (sin `python-dotenv`). **Las variables ya exportadas en la shell
tienen prioridad** sobre el archivo - util para sobreescribir en CI sin
tocar el `.env`.

| Variable | Obligatoria | Formato / ejemplo | De donde sale |
|---|---|---|---|
| `SPAPI_CLIENT_ID` | **si** | `amzn1.application-oa2-client.<32 hex>` (61 car.) | Solution Provider Portal -> tu app |
| `SPAPI_CLIENT_SECRET` | **si** | `amzn1.oa2-cs.v1.<64 hex>` (80 car.) | idem, se muestra una sola vez |
| `SPAPI_REFRESH_TOKEN` | **si** | `Atzr\|IwEBI...` (~330 car.) | Vendor Central -> Central de Desarrolladores -> **Autorizar** |
| `SPAPI_ENDPOINT` | no | `https://sellingpartnerapi-na.amazon.com` | fijo por region |
| `SPAPI_LWA_ENDPOINT` | no | `https://api.amazon.com/auth/o2/token` | fijo |
| `SPAPI_MARKETPLACE_ID` | no | `A1AM78C64UM0Y8` | fijo para MX |
| `SPAPI_TEST_DAYS_BACK` | no | `7` | dias hacia atras por defecto |

Las tres obligatorias se validan en `settings.missing_credentials()`, que
devuelve los nombres faltantes; `check_auth.py` y `LwaAuth` cortan con un
mensaje claro antes de intentar la llamada.

### Constante no configurable

`DATA_LAG_DAYS = 3` en `config/settings.py`. Amazon publica los datos de un
dia hasta **~34 horas despues** (10am hora local, dos dias despues). Por eso
`default_date_range()` calcula el rango terminando 3 dias atras, nunca
"ayer". Pedir datos dentro del lag devuelve vacio o incompleto, **sin
error** - es la fuente de confusion mas comun.

---

## 5. Opcion A - Reports API (`/reports/2021-06-30`)

### 5.1 Operaciones y parametros

#### `POST /reports/2021-06-30/reports` - createReport

Cuerpo JSON:

| Campo | Tipo | Obligatorio | Detalle |
|---|---|---|---|
| `reportType` | string | si | `GET_VENDOR_SALES_REPORT` / `GET_VENDOR_INVENTORY_REPORT` |
| `marketplaceIds` | array | si | `["A1AM78C64UM0Y8"]` |
| `dataStartTime` | ISO 8601 | si | `2026-08-16T00:00:00Z` |
| `dataEndTime` | ISO 8601 | si | `2026-08-22T23:59:59Z` |
| `reportOptions` | objeto | **si, para vendor** | ver abajo |

**`reportOptions` - las tres son obligatorias.** Omitir cualquiera hace que
`createReport` devuelva **400**. Esto no esta bien destacado en la
documentacion y fue un bug real del proyecto. **Verificado.**

| Opcion | Valores | Que significa |
|---|---|---|
| `reportPeriod` | `DAY`, `WEEK`, `MONTH`, `QUARTER`, `YEAR` | granularidad de las filas |
| `distributorView` | `SOURCING`, `MANUFACTURING` | `SOURCING` = lo que Amazon te compra a vos (es el que usa Acer MX) |
| `sellingProgram` | `RETAIL`, `BUSINESS`, `FRESH` | programa de venta; Acer MX usa `RETAIL` |

Respuesta (202): `{"reportId": "51191020691"}`

#### `GET /reports/2021-06-30/reports/{reportId}` - getReport

Devuelve el estado. **Verificado**, respuesta real:

```json
{
  "reportType": "GET_VENDOR_SALES_REPORT",
  "processingStatus": "DONE",
  "marketplaceIds": ["A1AM78C64UM0Y8"],
  "reportDocumentId": "amzn1.spdoc.1.4.na.0a920b7a-....43400",
  "reportId": "51191020691",
  "dataStartTime": "2026-08-16T00:00:00+00:00",
  "dataEndTime": "2026-08-22T23:59:59+00:00",
  "createdTime": "2026-08-26T23:47:19+00:00",
  "processingStartTime": "2026-08-26T23:47:28+00:00",
  "processingEndTime": "2026-08-26T23:47:49+00:00"
}
```

`processingStatus`: `IN_QUEUE` -> `IN_PROGRESS` -> `DONE` | `CANCELLED` |
`FATAL`. Los tres ultimos son terminales. `reportDocumentId` solo aparece
en `DONE`.

**Tiempo observado: menos de 1 minuto** para ambos reportes.

#### `GET /reports/2021-06-30/documents/{reportDocumentId}` - getReportDocument

**Verificado**, respuesta real:

```json
{
  "reportDocumentId": "amzn1.spdoc.1.4.na....",
  "compressionAlgorithm": "GZIP",
  "url": "https://tortuga-prod-na.s3-external-1.amazonaws.com/..."
}
```

La `url` es prefirmada y **caduca en ~5 minutos**. Hay que descargarla en
el momento. Si `compressionAlgorithm` es `GZIP` hay que descomprimir; si el
campo no viene, el contenido es texto plano. Los reportes de vendor de Acer
MX llegan **GZIP**.

### 5.2 Que se baja en crudo

**JSON plano** (no TSV, no CSV). Tres claves en la raiz.

#### `GET_VENDOR_SALES_REPORT`

```json
{
  "reportSpecification": {
    "reportType": "GET_VENDOR_SALES_REPORT",
    "reportOptions": {"reportPeriod":"DAY","sellingProgram":"RETAIL","distributorView":"SOURCING"},
    "dataStartTime": "2026-08-16", "dataEndTime": "2026-08-22",
    "marketplaceIds": ["A1AM78C64UM0Y8"]
  },
  "salesAggregate": [ "... una fila por dia, totales ..." ],
  "salesByAsin": [
    {
      "startDate": "2026-08-23", "endDate": "2026-08-23",
      "asin": "B08QTRC5DX",
      "customerReturns": 0,
      "shippedCogs":    {"amount": 775.08, "currencyCode": "MXN"},
      "shippedRevenue": {"amount": 732.50, "currencyCode": "MXN"},
      "shippedUnits": 1
    }
  ]
}
```

7 campos en `salesByAsin[]`, ninguno nulo en la muestra. Los montos son
objetos `{amount, currencyCode}`, no numeros sueltos.

> Con `distributorView: SOURCING` **no existen** `orderedUnits` ni
> `orderedRevenue` - son de la vista `MANUFACTURING`. El sell-out es
> `shippedUnits`.

#### `GET_VENDOR_INVENTORY_REPORT`

Mismas tres claves (`reportSpecification`, `inventoryAggregate`,
`inventoryByAsin`). **22 campos** por fila:

`startDate`, `endDate`, `asin`, `sourceableProductOutOfStockRate`,
`procurableProductOutOfStockRate`, `openPurchaseOrderUnits`,
`receiveFillRate`, `averageVendorLeadTimeDays`, `sellThroughRate`,
`unfilledCustomerOrderedUnits`, `vendorConfirmationRate`,
`netReceivedInventoryCost`, `netReceivedInventoryUnits`,
`sellableOnHandInventoryCost`, **`sellableOnHandInventoryUnits`**,
`unsellableOnHandInventoryCost`, `unsellableOnHandInventoryUnits`,
`aged90PlusDaysSellableInventoryCost`, `aged90PlusDaysSellableInventoryUnits`,
`unhealthyInventoryCost`, `unhealthyInventoryUnits`, `uft`.

> **Cuidado con los nulos.** A nivel ASIN, `sellThroughRate`,
> `openPurchaseOrderUnits` y `sourceableProductOutOfStockRate` vienen
> frecuentemente `null`, no `0`. El loader tiene que tolerarlo.

> **Cobertura desigual.** En la muestra, 34 ASINs estaban en inventario sin
> fila en ventas. No asumir el mismo universo de ASINs entre reportes.

---

## 6. Opcion B - Data Kiosk (`/dataKiosk/2023-11-15`)

### 6.1 Operaciones

| Operacion | Metodo y ruta | Cuerpo / respuesta |
|---|---|---|
| createQuery | `POST /dataKiosk/2023-11-15/queries` | `{"query": "<graphql>"}` -> `{"queryId": "..."}` |
| getQuery | `GET /dataKiosk/2023-11-15/queries/{queryId}` | estado + `dataDocumentId` o `errorDocumentId` |
| getDocument | `GET /dataKiosk/2023-11-15/documents/{documentId}` | `{"documentUrl": "..."}` |

> Diferencia con Reports API: el campo de la URL se llama **`documentUrl`**,
> no `url`.

Estados: los mismos cinco. **Tiempo observado: 40-60 s.**

### 6.2 Manejo de errores - critico

Data Kiosk falla en **dos momentos distintos**:

1. **Validacion (inmediata, HTTP 400).** Error de sintaxis o campo
   inexistente. Se ve al toque en la respuesta de `createQuery`.
2. **Procesamiento (asincrono, `processingStatus: FATAL`).** La query era
   sintacticamente valida pero viola una regla de negocio. **El motivo real
   solo esta en el documento apuntado por `errorDocumentId`** - hay que
   descargarlo o solo se ve la palabra `FATAL`.

Ejemplo real de documento de error:

```json
[{"message":"Exception while fetching data (/analytics_vendorAnalytics_2024_09_30/sourcingView) : The same start and end dates must be requested for Daily Inventory metrics.",
  "extensions":{"classification":"DataFetchingException"}}]
```

`ejecutar()` en [`spapi/data_kiosk.py`](../spapi/data_kiosk.py) descarga e
imprime ese documento automaticamente.

### 6.3 El schema GraphQL

Dominio: **`analytics_vendorAnalytics_2024_09_30`**.

> **La introspeccion GraphQL esta bloqueada** ("Query did not have a
> versioned domain field"), y adivinar nombres cuesta una query por intento.
> Trabajar siempre contra el schema oficial:
> `github.com/amzn/selling-partner-api-models` ->
> `schemas/data-kiosk/analytics_vendorAnalytics_2024_09_30.graphql`.
> Conviene fijar una copia en el repo.

Campos de primer nivel del dominio:

| Campo | Equivale a |
|---|---|
| `sourcingView` | `distributorView: SOURCING` del Reports API <- **el que usa Acer MX** |
| `manufacturingView` | `distributorView: MANUFACTURING` |

Argumentos de la vista:

| Argumento | Tipo | Obligatorio | Valores |
|---|---|---|---|
| `startDate` | Date! | si | `"2026-08-17"` |
| `endDate` | Date! | si | maximo 2 anios atras |
| `aggregateBy` | DateGranularity! | si | `DAY`, `WEEK`, `MONTH` |
| `currencyCode` | String | no | ISO 4217; **default USD** - poner `"MXN"` |

> Ojo con el nombre: es `aggregateBy`, **no** `aggregatedBy`.

Estructura de la respuesta de la vista:

```
sourcingView
+-- startDate, endDate, marketplaceId
+-- totals   : SourcingViewMetrics          (agregado de todo)
+-- metrics  : [SourcingViewMetricsGroupedBy]
    +-- groupByKey : GroupByAttributes
    +-- metrics    : SourcingViewMetrics
```

`SourcingViewMetrics` agrupa: `shippedOrders` (sell-out),
`productAvailability` (inventario), `costs`, `sourcing`,
`customerSatisfaction`.

`GroupByAttributes` tiene 24 campos. Los relevantes: **`asin`**,
**`modelNumber`**, `brand`, `brandCode`, `productTitle`, `upc`, `ean`,
`vendorCode`, `parentAsin`, `productGroup`, `manufacturerCode`, `msrp`.

Campos usados por este proyecto:

```
shippedOrders.shippedUnitsWithRevenue.units        -> sell-out
shippedOrders.shippedUnitsWithRevenue.value        -> {amount, currencyCode}
shippedOrders.averageSellingPrice                  -> {amount, currencyCode}
productAvailability.sellableOnHandInventory.units  -> inventario
productAvailability.unsellableOnHandInventory.units
productAvailability.sellableInTransitInventory     -> Long suelto
productAvailability.sellThroughRate                -> Float suelto
```

### 6.4 Las dos restricciones que sorprenden

**(a) Un solo campo de primer nivel por dominio.**
Pedir `sourcingView` y `manufacturingView` juntos -> 400
*"Versioned domain cannot select multiple query fields"*.

En la practica no molesta: sell-out e inventario viven **ambos** dentro de
`metrics` de una misma vista, asi que **una sola query si trae los dos**.

**(b) Inventario diario exige `startDate == endDate`.**
Con `aggregateBy: DAY`, pedir `productAvailability` sobre un rango falla
como **FATAL en procesamiento** (no 400 - o sea, se pierde el minuto de la
query antes de enterarse). N dias de historia de inventario = N queries.

Codificado como guardia en `query_sales_e_inventory()`, que lanza
`ValueError` antes de gastar la llamada. Para rangos multi-dia de solo
ventas existe `query_solo_ventas()`.

### 6.5 Que se baja en crudo

**JSONL** sin comprimir. La trampa: **es una linea por bucket de fecha**,
con los ASINs anidados adentro. No es una linea por registro.

```json
{"startDate":"2026-08-17","endDate":"2026-08-17","marketplaceId":"A1AM78C64UM0Y8",
 "metrics":[
   {"groupByKey":{"asin":"B0FDLW5T5H","modelNumber":"NX.D4CAL.002","brand":"acer"},
    "metrics":{"shippedOrders":{"shippedUnitsWithRevenue":{"units":2,"value":{"amount":25860.34,"currencyCode":"MXN"}}}}},
   {"groupByKey":{"asin":"B0FJS8675G","modelNumber":"PM161QT bmiuuux","brand":"acer"},
    "metrics":{}}
 ]}
```

Una query de 7 dias = **7 lineas**, con 69 registros repartidos adentro. El
loader tiene que aplanar `linea.metrics[]`.

Igual que en el Reports API, `units` viene **`null`**, no `0`, cuando no
hay dato (129 de 186 registros de inventario en la muestra de un dia).

---

## 7. Rate limits

Valores oficiales del modelo de la API (`selling-partner-api-models`).
Token bucket: `rate` es la reposicion sostenida en req/s, `burst` es el
tamano del balde.

| Operacion | Rate (req/s) | Burst | En claro |
|---|---|---|---|
| `createReport` | 0.0167 | 15 | **1 por minuto** |
| `getReport` | 2.0 | 15 | 2 por segundo - el polling es barato |
| `getReportDocument` | 0.0167 | 15 | **1 por minuto** |
| `getReports` | 0.0222 | 10 | ~1.3 por minuto |
| `createQuery` | 0.0167 | 15 | **1 por minuto** |
| `getQuery` | 2.0 | 15 | 2 por segundo |
| `getDocument` | 0.0167 | 15 | **1 por minuto** |

Lo que importa en la practica: **crear trabajos y descargar documentos esta
limitado a ~1/minuto; el polling no**. Iterar dia por dia (por ejemplo para
historia de inventario en Data Kiosk) consume el burst rapido.

`SpApiClient.request()` reintenta ante **429 y 5xx** con backoff
exponencial mas jitter (`2^intento + random(0,1)`), hasta 6 intentos -
unos 63 s acumulados. Un 429 no es un error: es el comportamiento esperado
del token bucket.

---

## 8. Errores observados y que significan

| Sintoma | Causa | Solucion |
|---|---|---|
| `400` en createReport | falta `sellingProgram` en `reportOptions` | mandar las tres opciones |
| `401 invalid_client` (LWA) | client_id/secret mal | revisar `.env` |
| `400 invalid_grant` (LWA) | refresh token revocado o de otra app | rehacer el self-authorization |
| `403` en Data Kiosk | falta el rol **Brand Analytics** | pedirlo en el perfil de desarrollador y re-autorizar |
| `400` *"Versioned domain cannot select multiple query fields"* | dos campos de primer nivel | dejar una sola vista |
| `FATAL` *"The same start and end dates..."* | inventario diario con rango | `startDate == endDate` |
| `400 FieldUndefined` | nombre de campo inventado | usar el schema oficial |
| Reporte `DONE` pero vacio | rango dentro del lag de ~34 h | respetar `DATA_LAG_DAYS` |
| Datos vacios sin error | endpoint y marketplace incoherentes | NA + `A1AM78C64UM0Y8` |

---

## 9. Scripts y sus parametros

Todos guardan la salida cruda en `out/` (ignorado por git).

| Script | Parametros | Que hace / que deja |
|---|---|---|
| `check_auth.py` | ninguno | Valida `.env`, pide access token, lista reportes recientes. Salida solo por consola. |
| `explore_reports.py` | `--days N` | Baja los dos reportes vendor. Deja `reports_sales_<ts>.json` y `reports_inventory_<ts>.json`. |
| `explore_data_kiosk.py` | `--days N`, `--solo-ventas`, `--print-query` | Sin `--solo-ventas` pide ventas+inventario de **un solo dia**. Deja `datakiosk_<ts>.jsonl`. `--print-query` imprime la GraphQL sin llamar. |
| `build_semanal.py` | `--semana N --anio A`, o `--desde/--hasta`, `--diario` | Genera el CSV del pipeline. Deja `so_wk_NN_AAAA.csv` con `customer_code,report_type,partnumber,units,date_id`. |

### Modulos

| Modulo | Responsabilidad |
|---|---|
| `config/settings.py` | Carga del `.env`, rangos de fecha con lag, validacion de credenciales |
| `spapi/auth.py` | LWA: refresh token -> access token, con cache y renovacion |
| `spapi/client.py` | HTTP, header de token, backoff 429/5xx, descarga de documentos, `guardar_salida()` |
| `spapi/reports.py` | Opcion A: `crear_reporte` / `esperar_reporte` / `descargar_documento` / `obtener_reporte` |
| `spapi/data_kiosk.py` | Opcion B: construccion de queries, guardia de fechas, polling, documentos de error |

---

## 10. Semana Amazon vs semana ISO

Detalle que no es de la API pero afecta todo el pipeline. **Verificado.**

La descarga manual de Vendor Central usa la **semana de Amazon
(domingo->sabado)**. El pipeline ACER usa **semana ISO (lunes->domingo)**.

El archivo `Amazon_SO_WTD_Ventas_2026_08_23.xlsx` dice por dentro
`Rango de visualizacion=[16/08/26 - 22/08/26]` - domingo 16 a sabado 22, no
lunes 17 a domingo 23. Un dia de desfase en cada punta respecto a
`so_wk_34_2026`.

La API entrega **granularidad diaria**, asi que se puede reagrupar por
semana ISO. Es la ganancia mas concreta del cambio, mas alla de la
automatizacion: la descarga manual no permite re-cortar la semana.

### Equivalencia verificada

Pidiendo a la API la misma ventana que trae el xlsx (16->22 ago):

| | XLSX manual | API | |
|---|---|---|---|
| Ventas: ASINs | 28 | 28 | coincide ASIN por ASIN |
| Ventas: unidades | 133 | 133 | exacto |
| Inventario: unidades | 4418 | 4418 | exacto |

La unica diferencia es de forma: el xlsx incluye 6 ASINs con `0`, la API
los omite.
