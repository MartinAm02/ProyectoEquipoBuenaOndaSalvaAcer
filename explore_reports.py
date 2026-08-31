"""Opcion A: baja GET_VENDOR_SALES_REPORT y GET_VENDOR_INVENTORY_REPORT.

Solo inspeccion: guarda el output crudo en out/ y muestra las primeras
lineas. No toca la base de datos.

    python explore_reports.py [--days 7]
"""

import argparse
from datetime import datetime

from config import settings
from spapi import reports
from spapi.client import SpApiClient, SpApiError, guardar_salida


def _vista_previa(contenido: str, lineas: int = 5) -> None:
    for linea in contenido.splitlines()[:lineas]:
        print(f"  | {linea[:300]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba del Reports API clasico")
    parser.add_argument("--days", type=int, default=None, help="dias hacia atras")
    args = parser.parse_args()

    inicio, fin = settings.default_date_range(args.days)
    client = SpApiClient()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")

    for report_type, sufijo in (
        (reports.SALES_REPORT, "sales"),
        (reports.INVENTORY_REPORT, "inventory"),
    ):
        try:
            contenido = reports.obtener_reporte(client, report_type, inicio, fin)
        except (SpApiError, TimeoutError) as exc:
            print(f"  ERROR en {report_type}: {exc}")
            continue
        if not contenido:
            continue
        guardar_salida(f"reports_{sufijo}_{sello}.json", contenido)
        _vista_previa(contenido)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
