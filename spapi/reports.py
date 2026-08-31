"""Opcion A: Reports API clasico (dos reportes separados).

Flujo asincrono: createReport -> polling getReport -> getReportDocument.
GET_VENDOR_SALES_REPORT y GET_VENDOR_INVENTORY_REPORT son reportes de
categoria Analytics, exclusivos para vendors.
"""

import gzip
import time
from datetime import date, datetime, time as _time, timezone

from config import settings
from spapi.client import SpApiClient


REPORTS_PATH = "/reports/2021-06-30/reports"
DOCUMENTS_PATH = "/reports/2021-06-30/documents"

SALES_REPORT = "GET_VENDOR_SALES_REPORT"
INVENTORY_REPORT = "GET_VENDOR_INVENTORY_REPORT"

ESTADOS_FINALES = {"DONE", "CANCELLED", "FATAL"}

# Los tres reportOptions son OBLIGATORIOS para los reportes de vendor:
# omitir sellingProgram hace que createReport devuelva 400.
#   reportPeriod    DAY | WEEK | MONTH | QUARTER | YEAR
#   distributorView MANUFACTURING | SOURCING
#   sellingProgram  RETAIL | BUSINESS | FRESH
REPORT_OPTIONS_DEFECTO = {
    "reportPeriod": "DAY",
    "distributorView": "SOURCING",
    "sellingProgram": "RETAIL",
}


def _iso(dia: date, fin: bool = False) -> str:
    momento = _time.max if fin else _time.min
    return datetime.combine(dia, momento, tzinfo=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def crear_reporte(
    client: SpApiClient,
    report_type: str,
    inicio: date,
    fin: date,
    opciones: dict | None = None,
) -> str:
    """Solicita el reporte y devuelve el reportId."""
    payload = {
        "reportType": report_type,
        "marketplaceIds": [settings.MARKETPLACE_ID],
        "dataStartTime": _iso(inicio),
        "dataEndTime": _iso(fin, fin=True),
        # Granularidad diaria por SKU: es lo que mapea al reporte semanal
        # so_wk_XX_2026.csv (una fila por partnumber y date_id).
        "reportOptions": opciones or dict(REPORT_OPTIONS_DEFECTO),
    }
    respuesta = client.post_json(REPORTS_PATH, payload)
    report_id = respuesta["reportId"]
    print(f"  reportId={report_id}")
    return report_id


def esperar_reporte(
    client: SpApiClient, report_id: str, timeout_s: int = 900, intervalo_s: int = 30
) -> dict:
    """Hace polling hasta que el reporte llega a un estado final."""
    limite = time.time() + timeout_s
    while time.time() < limite:
        estado = client.get_json(f"{REPORTS_PATH}/{report_id}")
        processing = estado.get("processingStatus")
        print(f"  processingStatus={processing}")
        if processing in ESTADOS_FINALES:
            return estado
        time.sleep(intervalo_s)
    raise TimeoutError(f"El reporte {report_id} no termino en {timeout_s}s")


def descargar_documento(client: SpApiClient, document_id: str) -> str:
    """Descarga y descomprime el documento del reporte."""
    documento = client.get_json(f"{DOCUMENTS_PATH}/{document_id}")
    crudo = client.download(documento["url"])
    if documento.get("compressionAlgorithm") == "GZIP":
        crudo = gzip.decompress(crudo)
    return crudo.decode("utf-8", errors="replace")


def obtener_reporte(
    client: SpApiClient, report_type: str, inicio: date, fin: date
) -> str | None:
    """createReport + polling + descarga. Devuelve el contenido o None."""
    print(f"[Reports API] {report_type} {inicio} -> {fin}")
    report_id = crear_reporte(client, report_type, inicio, fin)
    estado = esperar_reporte(client, report_id)
    if estado.get("processingStatus") != "DONE":
        # Un FATAL igual trae reportDocumentId, y ahi esta el motivo real
        # (rango no disponible todavia, opciones invalidas, etc). Sin esto
        # solo se ve la palabra FATAL y no se puede diagnosticar nada.
        print(f"  reporte {estado.get('processingStatus')}")
        doc_id = estado.get("reportDocumentId")
        if doc_id:
            print("  motivo:", descargar_documento(client, doc_id)[:600])
        return None
    return descargar_documento(client, estado["reportDocumentId"])
