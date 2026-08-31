"""Opcion B: Data Kiosk (GraphQL) sobre Cross-Domain Vendor Analytics.

Permite pedir sales + inventory en UNA sola consulta. Requiere el rol
"Brand Analytics" en la aplicacion. Los datos de un dia estan disponibles
hasta ~34h despues (10am hora local, dos dias despues).

Flujo asincrono: createQuery -> polling getQuery -> descarga JSONL.
"""

import time
from datetime import date

from spapi.client import SpApiClient


QUERIES_PATH = "/dataKiosk/2023-11-15/queries"
DOCUMENTS_PATH = "/dataKiosk/2023-11-15/documents"

ESTADOS_FINALES = {"DONE", "CANCELLED", "FATAL"}


def query_sales_e_inventory(
    inicio: date, fin: date, vista: str = "sourcingView", moneda: str = "MXN"
) -> str:
    """GraphQL: sell-out + inventario por dia y ASIN, en UNA sola llamada.

    Un dominio versionado solo admite UN campo de primer nivel, asi que no
    se pueden pedir `sourcingView` y `manufacturingView` en la misma query.
    Pero eso no importa: dentro de la vista, `shippedOrders` (sell-out) y
    `productAvailability` (inventario) conviven en el mismo bloque
    `metrics`, asi que una sola query trae ambos.

    `sourcingView` es el equivalente al `distributorView: SOURCING` del
    Reports API. `modelNumber` en `groupByKey` es el candidato natural para
    resolver ASIN -> partnumber Acer sin tabla de equivalencia aparte.
    """
    if inicio != fin:
        raise ValueError(
            "Con aggregateBy: DAY las metricas de inventario exigen "
            f"startDate == endDate (se pidio {inicio} -> {fin}). Para un "
            "rango multi-dia usa query_solo_ventas(), o itera por dia."
        )
    return f"""
query SellOutInventory {{
  analytics_vendorAnalytics_2024_09_30 {{
    {vista}(
      startDate: "{inicio.isoformat()}"
      endDate: "{fin.isoformat()}"
      aggregateBy: DAY
      currencyCode: "{moneda}"
    ) {{
      startDate
      endDate
      marketplaceId
      metrics {{
        groupByKey {{
          asin
          modelNumber
          brand
          productTitle
        }}
        metrics {{
          shippedOrders {{
            shippedUnitsWithRevenue {{
              units
              value {{ amount currencyCode }}
            }}
            averageSellingPrice {{ amount currencyCode }}
          }}
          productAvailability {{
            sellableOnHandInventory {{
              units
              value {{ amount currencyCode }}
            }}
            unsellableOnHandInventory {{ units }}
            sellableInTransitInventory
            sellThroughRate
          }}
        }}
      }}
    }}
  }}
}}
""".strip()


def crear_query(client: SpApiClient, query: str) -> str:
    respuesta = client.post_json(QUERIES_PATH, {"query": query})
    query_id = respuesta["queryId"]
    print(f"  queryId={query_id}")
    return query_id


def esperar_query(
    client: SpApiClient, query_id: str, timeout_s: int = 900, intervalo_s: int = 30
) -> dict:
    limite = time.time() + timeout_s
    while time.time() < limite:
        estado = client.get_json(f"{QUERIES_PATH}/{query_id}")
        processing = estado.get("processingStatus")
        print(f"  processingStatus={processing}")
        if processing in ESTADOS_FINALES:
            return estado
        time.sleep(intervalo_s)
    raise TimeoutError(f"La query {query_id} no termino en {timeout_s}s")


def descargar_documento(client: SpApiClient, document_id: str) -> str:
    documento = client.get_json(f"{DOCUMENTS_PATH}/{document_id}")
    return client.download(documento["documentUrl"]).decode("utf-8", errors="replace")


def ejecutar(
    client: SpApiClient, inicio: date, fin: date, solo_ventas: bool = False
) -> str | None:
    """createQuery + polling + descarga del JSONL. Devuelve el contenido."""
    if solo_ventas:
        print(f"[Data Kiosk] solo shippedOrders {inicio} -> {fin}")
        query = query_solo_ventas(inicio, fin)
    else:
        print(f"[Data Kiosk] shippedOrders + productAvailability {inicio}")
        query = query_sales_e_inventory(inicio, fin)

    query_id = crear_query(client, query)
    estado = esperar_query(client, query_id)

    # Un FATAL trae el motivo real en errorDocumentId; sin esto solo se ve
    # "FATAL" y no se puede diagnosticar nada.
    if estado.get("processingStatus") != "DONE":
        print(f"  query {estado.get('processingStatus')}")
        error_id = estado.get("errorDocumentId")
        if error_id:
            print("  motivo:", descargar_documento(client, error_id)[:1000])
        return None

    document_id = estado.get("dataDocumentId")
    if not document_id:
        # DONE sin documento = la query corrio pero no hubo filas.
        print("  query DONE sin documento (sin datos en el rango)")
        return None
    return descargar_documento(client, document_id)


def query_solo_ventas(
    inicio: date, fin: date, vista: str = "sourcingView", moneda: str = "MXN"
) -> str:
    """Solo sell-out. Sin metricas de inventario admite rangos multi-dia."""
    return f"""
query SellOut {{
  analytics_vendorAnalytics_2024_09_30 {{
    {vista}(
      startDate: "{inicio.isoformat()}"
      endDate: "{fin.isoformat()}"
      aggregateBy: DAY
      currencyCode: "{moneda}"
    ) {{
      startDate
      endDate
      marketplaceId
      metrics {{
        groupByKey {{
          asin
          modelNumber
          brand
          productTitle
        }}
        metrics {{
          shippedOrders {{
            shippedUnitsWithRevenue {{
              units
              value {{ amount currencyCode }}
            }}
            averageSellingPrice {{ amount currencyCode }}
          }}
        }}
      }}
    }}
  }}
}}
""".strip()
