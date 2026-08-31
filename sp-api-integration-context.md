# Contexto: Integración Amazon SP-API — Sell-Out e Inventario (Acer México)

## Objetivo de esta sesión

Antes de construir el flujo de automatización final, necesitamos **explorar qué devuelve realmente la API** para decidir cómo integrarla al pipeline existente. Concretamente:

1. Autenticarnos contra el SP-API con las credenciales que ya tenemos aprobadas.
2. Hacer llamadas de prueba para ver la forma real de los datos (no solo lo que dice la documentación).
3. Determinar si conviene usar el **Reports API clásico** (dos reportes separados) o el **Data Kiosk (GraphQL)**, que puede traer sell-out e inventario **en una sola consulta**.
4. Con eso decidido, diseñar cómo se integra al reporte actual (`so_wk_XX_2026.csv` y la tabla que alimenta la base de datos vía UPSERT).

No estamos listos para automatizar en producción todavía — esta fase es de **descubrimiento y prototipo**.

## Contexto del proyecto

- Trabajamos en el equipo de datos/analítica de Acer México, manteniendo el pipeline **ACER Report Loader** (PostgreSQL + Python), que carga datos de sell-out e inventario de distintos canales (Exel/disty, y ahora Amazon).
- Actualmente, para el canal Exel, se construyen reportes semanales `so_wk_XX_2026.csv` con columnas `customer_code, report_type, partnumber, units, date_id`. La fuente ya estructurada para eso es el reporte "Mexico Channel Sell Thru" (Vision).
- El objetivo con Amazon es replicar ese mismo patrón: sell-out semanal e inventario por SKU, pero obtenido automáticamente vía API en lugar de descarga manual desde Vendor Central.
- La base de datos ya usa lógica **UPSERT** para manejar registros duplicados de forma segura — cualquier nueva fuente de datos debe respetar ese mismo patrón de idempotencia.

## Estado del acceso a Amazon

- Cuenta de **Vendor Central México** con rol de administrador.
- **Solicitud de acceso a SP-API ya APROBADA** por Amazon (Solution Provider Portal → Central de desarrolladores).
- Se registró una aplicación de tipo **Producción** (no Sandbox) bajo "API de SP", con nombre descriptivo interno (ej. `Acer MX Sell-Out Inventory Loader`).
- **Pendiente:** completar el flujo de self-authorization para obtener `Client ID`, `Client Secret` y `Refresh Token`. Guía oficial: `https://developer-docs.amazon.com/sp-api/docs/registering-your-application`.
- Región/marketplace: **México (NA)** — endpoint base `https://sellingpartnerapi-na.amazon.com`.

## Dos caminos posibles para obtener sell-out + inventario

### Opción A — Reports API (clásico)

Requiere **dos solicitudes de reporte separadas** (no se puede combinar en una sola llamada):

- `GET_VENDOR_SALES_REPORT` → sell-out.
- `GET_VENDOR_INVENTORY_REPORT` → inventario.

Flujo: `createReport` → polling de estado (`getReport`) → `getReportDocument` para descargar. Es asíncrono; los reportes pueden tardar minutos en generarse. Ambos reportes están bajo la categoría "Analytics" y son exclusivos para vendors.

### Opción B — Data Kiosk (GraphQL) — probablemente la mejor opción

Data Kiosk permite consultas **GraphQL personalizadas** contra el dataset **Cross-Domain Vendor Analytics**, que combina en una sola consulta métricas de:

- Sales (sell-out)
- Inventory
- Traffic
- Forecast

... agregadas por fecha, ASIN, marca, etc. Esto **sí responde directamente a la pregunta de si se puede sacar todo en una sola llamada** — con Data Kiosk, sí.

Consideraciones importantes:

- Requiere el **rol "Brand Analytics"** asignado a la aplicación (verificar si ya lo tienen o hay que solicitarlo por separado en el perfil de desarrollador).
- Los datos tardan **hasta 34 horas** en estar disponibles (no es tiempo real) — los datos de un día están listos a las 10am hora local, dos días después.
- El flujo también es asíncrono: se crea la query, se espera notificación o se hace polling, y se descarga un documento en formato **JSONL**.
- Amazon indica que el Reports API eventualmente será reemplazado por Data Kiosk para varios tipos de reporte — vale la pena evaluar si conviene empezar directo aquí en lugar de construir sobre algo que se va a deprecar.

**Tarea concreta para esta sesión:** probar ambos caminos con datos reales (llamadas mínimas, solo para inspeccionar el shape de la respuesta) y documentar cuál conviene más para el pipeline, antes de escribir el loader definitivo.

## Qué debe hacer el script de exploración

1. Implementar la autenticación LWA (access token vía refresh token) — usar variables de entorno, nunca credenciales hardcodeadas en el código (`Client ID`, `Client Secret`, `Refresh Token` en un `.env`, excluido de git).
2. Hacer una llamada de prueba a `GET_VENDOR_SALES_REPORT` y otra a `GET_VENDOR_INVENTORY_REPORT` vía Reports API, y guardar el output crudo (JSON/flat file) para inspección manual.
3. Hacer una consulta de prueba a Data Kiosk contra el dataset Vendor Analytics, pidiendo un rango corto de fechas y unas pocas métricas de sales + inventory, y comparar el resultado contra lo anterior.
4. No escribir aún lógica de UPSERT ni tocar la base de datos de producción — esto es solo para ver la forma de los datos.
5. Documentar en comentarios/README qué campos trae cada opción y cuáles mapean directamente a las columnas que ya usamos (`customer_code`, `report_type`, `partnumber`, `units`, `date_id`).

## Restricciones y buenas prácticas (aplican siempre)

- Nada de scraping ni acceso no oficial — solo SP-API con las credenciales propias y aprobadas.
- Respetar los rate limits documentados (token bucket, por operación) — implementar backoff ante errores 429.
- Seguir el principio de "need to know": solo pedir los roles/scopes de API que realmente se van a usar.
- Rotar credenciales según la política de seguridad de Amazon (SP-API: cada 12 meses; Ads API: consentimiento anual — aplica cuando se integre esa parte).
- Todo el código y credenciales deben quedar en el repo del ACER Report Loader, siguiendo la misma estructura de configuración que ya existe (conexión a Postgres vía extensión de VS Code).

## Referencias oficiales usadas

- What is the Selling Partner API — `https://developer-docs.amazon.com/sp-api/docs/what-is-the-selling-partner-api`
- SP-API SDKs — `https://developer-docs.amazon.com/sp-api/docs/sp-api-sdks`
- SP-API Sandbox — `https://developer-docs.amazon.com/sp-api/docs/sp-api-sandbox`
- Data Kiosk API — `https://developer-docs.amazon.com/sp-api/docs/data-kiosk-api`
- Data Kiosk Schema Explorer — `https://developer-docs.amazon.com/sp-api/docs/schema-explorer-guide`
- Onboarding as a Developer — `https://developer-docs.amazon.com/sp-api/docs/onboarding-overview`
- Report Type Values — `https://developer-docs.amazon.com/sp-api/docs/report-type-values`
- Vendor Analytics Dataset Use Case Guide — `https://developer-docs.amazon.com/sp-api/docs/vendor-analytics-dataset-guide`
- Registering your Application — `https://developer-docs.amazon.com/sp-api/docs/registering-your-application`
