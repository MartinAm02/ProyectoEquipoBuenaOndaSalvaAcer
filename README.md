# ACER SP-API Explorer

Fase de **descubrimiento y prototipo** para la integracion de Amazon
Vendor Central (Acer Mexico) al pipeline ACER Report Loader.

El objetivo NO es automatizar todavia, sino ver la forma real de los datos
y decidir entre dos caminos:

- **Opcion A — Reports API clasico**: dos reportes separados
  (`GET_VENDOR_SALES_REPORT` + `GET_VENDOR_INVENTORY_REPORT`).
- **Opcion B — Data Kiosk (GraphQL)**: sell-out e inventario en **una sola
  consulta** contra el dataset Cross-Domain Vendor Analytics.

Este proyecto vive fuera del repo del ACER Report Loader a proposito: es
codigo exploratorio y no toca la base de datos de produccion.

## Estructura

```
config/settings.py      carga de .env y rangos de fecha de prueba
spapi/auth.py           LWA: refresh token -> access token
spapi/client.py         cliente HTTP con backoff ante 429/5xx
spapi/reports.py        Opcion A: createReport -> polling -> documento
spapi/data_kiosk.py     Opcion B: createQuery GraphQL -> polling -> JSONL
check_auth.py           valida credenciales y acceso al endpoint
explore_reports.py      corre la Opcion A y guarda el output crudo
explore_data_kiosk.py   corre la Opcion B y guarda el JSONL
build_semanal.py        arma el CSV del pipeline por semana ISO
docs/api.md             referencia tecnica completa de la SP-API
docs/mapeo_campos.md    que campo mapea a que columna del pipeline
docs/hallazgos.md       comparativa Reports API vs Data Kiosk y decision
out/                    salidas crudas (ignorado por git)
```

Referencia tecnica completa de la API (auth, endpoints, parametros,
formato crudo, rate limits): [docs/api.md](docs/api.md).

## Puesta en marcha

```powershell
cd C:\ACER\ACER_SPAPI_EXPLORER
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env    # y completar las credenciales
python check_auth.py
```

Las credenciales (`Client ID`, `Client Secret`, `Refresh Token`) salen del
flujo de self-authorization del Solution Provider Portal:
https://developer-docs.amazon.com/sp-api/docs/registering-your-application

El `.env` esta excluido de git — nunca hardcodear credenciales.

## Uso

```powershell
python explore_reports.py --days 7      # Opcion A
python explore_data_kiosk.py            # Opcion B: ventas+inv, UN dia
python explore_data_kiosk.py --solo-ventas --days 7   # solo sell-out
python explore_data_kiosk.py --print-query   # ver la GraphQL sin llamar
```

Ambos scripts son asincronos: crean la solicitud, hacen polling cada 30s
(hasta 15 min) y guardan el resultado en `out/` para inspeccion manual.

## Cosas a tener presentes

- **Lag de datos**: Data Kiosk publica los datos de un dia hasta ~34h
  despues (10am hora local, dos dias despues). Por eso el rango de prueba
  por defecto termina 3 dias atras (`DATA_LAG_DAYS` en `config/settings.py`).
- **Inventario diario en Data Kiosk**: con `aggregateBy: DAY`, las metricas
  de `productAvailability` exigen `startDate == endDate`. Un rango de N dias
  con inventario = N queries. El Reports API trae los N dias en un solo
  reporte. Por eso `explore_data_kiosk.py` pide un solo dia salvo que se
  use `--solo-ventas`.
- **Rol Brand Analytics**: Data Kiosk lo exige. Si `explore_data_kiosk.py`
  devuelve 403, hay que solicitarlo en el perfil de desarrollador.
- **Un solo campo por dominio**: `analytics_vendorAnalytics_2024_09_30` no
  admite `sourcingView` y `manufacturingView` en la misma query
  ("Versioned domain cannot select multiple query fields"). No es problema:
  sell-out (`shippedOrders`) e inventario (`productAvailability`) viven
  dentro del mismo `metrics` de una sola vista.
- **Rate limits**: token bucket por operacion; el cliente reintenta con
  backoff exponencial ante 429 y 5xx.
- **Rotacion de credenciales**: SP-API exige rotarlas cada 12 meses.
- **Marketplace MX**: `A1AM78C64UM0Y8`, region NA
  (`https://sellingpartnerapi-na.amazon.com`).

## Estado y siguiente paso

1. [x] Completar el self-authorization y llenar el `.env`.
2. [x] Correr `check_auth.py` y confirmar acceso — OK.
3. [x] Opcion A corrida con datos reales (2026-08-17 -> 2026-08-23):
   175 filas de ventas / 25 ASINs, 413 de inventario / 59 ASINs, en MXN.
   Ver [docs/hallazgos.md](docs/hallazgos.md).
4. [x] Opcion B corrida: las dos fuentes dan numeros identicos
   (131 unidades de sell-out, 4396 de inventario).
5. [x] **Decidido: Opcion B (Data Kiosk).** El factor decisivo es que
   devuelve `modelNumber` ademas del ASIN; el Reports API no. Motivos y
   riesgos en [docs/hallazgos.md](docs/hallazgos.md).
6. [ ] Resolver el ~54% de ASINs cuyo `modelNumber` no es un SKU Acer
   limpio (ver [docs/mapeo_campos.md](docs/mapeo_campos.md)).
7. [ ] Escribir el loader con UPSERT dentro del ACER Report Loader,
   clave `(customer_code, report_type, partnumber, date_id)`.

El Reports API queda como fallback de reconciliacion: es rapido, funciona,
y sirve para auditar los numeros del Data Kiosk.
