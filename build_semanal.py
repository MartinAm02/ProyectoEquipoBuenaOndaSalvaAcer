"""Genera el equivalente a Amazon_SO_WTD_* desde la API, en semana ISO.

A diferencia de la descarga manual de Vendor Central (que usa la semana de
Amazon, domingo->sabado), aca se piden dias sueltos y se agregan por semana
ISO (lunes->domingo), que es la que usa so_wk_XX_2026.csv.

    python build_semanal.py --semana 34            # ISO week 34 de 2026
    python build_semanal.py --desde 2026-08-17 --hasta 2026-08-23
    python build_semanal.py --semana 34 --diario   # una fila por dia

Salidas en out/:
    so_wk_34_2026.csv          customer_code,report_type,partnumber,units,date_id
    amazon_detalle_wk34.csv    detalle con asin/titulo para auditar el mapeo
"""

import argparse
import csv
import json
from collections import defaultdict
from datetime import date, timedelta

from config import settings
from spapi import reports
from spapi.client import SpApiClient


CUSTOMER_CODE = "AMAZON_MX"


def rango_iso(anio: int, semana: int) -> tuple[date, date]:
    """Lunes y domingo de una semana ISO."""
    lunes = date.fromisocalendar(anio, semana, 1)
    return lunes, lunes + timedelta(days=6)


def _filas_reporte(client: SpApiClient, tipo: str, ini: date, fin: date, bloque: str):
    crudo = reports.obtener_reporte(client, tipo, ini, fin)
    if not crudo:
        return []
    return json.loads(crudo).get(bloque, [])


def recolectar(client: SpApiClient, ini: date, fin: date) -> list[dict]:
    """Sell-out diario del rango + snapshot de inventario del dia de cierre."""
    filas = []

    # Sell-out: el reporte diario ya trae una fila por ASIN y por dia.
    for r in _filas_reporte(client, reports.SALES_REPORT, ini, fin, "salesByAsin"):
        filas.append({
            "report_type": "SELL_OUT",
            "asin": r["asin"],
            "date_id": r["startDate"],
            "units": r.get("shippedUnits") or 0,
            "revenue": (r.get("shippedRevenue") or {}).get("amount"),
        })

    # Inventario: snapshot, no acumulable. Solo el ultimo dia del rango.
    for r in _filas_reporte(client, reports.INVENTORY_REPORT, fin, fin, "inventoryByAsin"):
        filas.append({
            "report_type": "INVENTORY",
            "asin": r["asin"],
            "date_id": r["startDate"],
            "units": r.get("sellableOnHandInventoryUnits") or 0,
            "revenue": (r.get("sellableOnHandInventoryCost") or {}).get("amount"),
        })
    return filas


def agregar_semana(filas: list[dict], fin: date) -> list[dict]:
    """Suma el sell-out de la semana; el inventario se deja como snapshot.

    Sumar inventario a lo largo de la semana daria un numero sin sentido
    (contaria el mismo stock varias veces), por eso solo se agrega SELL_OUT.
    """
    acc: dict[tuple[str, str], int] = defaultdict(int)
    for f in filas:
        if f["report_type"] == "SELL_OUT":
            acc[("SELL_OUT", f["asin"])] += f["units"]
        else:
            acc[("INVENTORY", f["asin"])] = f["units"]
    return [
        {"report_type": t, "asin": a, "units": u, "date_id": fin.isoformat()}
        for (t, a), u in sorted(acc.items())
    ]


def escribir_csv(destino, filas, mapeo: dict[str, str] | None = None) -> None:
    mapeo = mapeo or {}
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ruta = settings.OUTPUT_DIR / destino
    with open(ruta, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["customer_code", "report_type", "partnumber", "units", "date_id"])
        for f in filas:
            w.writerow([
                CUSTOMER_CODE,
                f["report_type"],
                mapeo.get(f["asin"], f["asin"]),
                f["units"],
                f["date_id"],
            ])
    print(f"  -> {ruta} ({len(filas)} filas)")


def main() -> int:
    p = argparse.ArgumentParser(description="Sell-out e inventario Amazon por semana ISO")
    p.add_argument("--semana", type=int, help="numero de semana ISO")
    p.add_argument("--anio", type=int, default=date.today().year)
    p.add_argument("--desde", type=date.fromisoformat)
    p.add_argument("--hasta", type=date.fromisoformat)
    p.add_argument("--diario", action="store_true", help="no agregar; una fila por dia")
    args = p.parse_args()

    if args.semana:
        ini, fin = rango_iso(args.anio, args.semana)
        etiqueta = f"wk_{args.semana:02d}_{args.anio}"
    elif args.desde and args.hasta:
        ini, fin = args.desde, args.hasta
        etiqueta = f"{ini:%Y%m%d}_{fin:%Y%m%d}"
    else:
        p.error("indica --semana o --desde/--hasta")

    hoy = date.today()
    if fin > hoy - timedelta(days=settings.DATA_LAG_DAYS):
        print(f"AVISO: {fin} esta dentro del lag de ~{settings.DATA_LAG_DAYS} dias; "
              "los datos pueden venir incompletos o vacios.")

    print(f"Rango: {ini} ({ini:%a}) -> {fin} ({fin:%a})")
    client = SpApiClient()
    filas = recolectar(client, ini, fin)

    if args.diario:
        escribir_csv(f"amazon_diario_{etiqueta}.csv", filas)
    else:
        escribir_csv(f"so_{etiqueta}.csv", agregar_semana(filas, fin))

    so = [f for f in filas if f["report_type"] == "SELL_OUT"]
    inv = [f for f in filas if f["report_type"] == "INVENTORY"]
    print(f"  sell-out : {sum(f['units'] for f in so)} unidades, "
          f"{len({f['asin'] for f in so})} ASINs")
    print(f"  inventario: {sum(f['units'] for f in inv)} unidades al {fin}, "
          f"{len(inv)} ASINs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
