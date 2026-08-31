"""Opcion B: una sola query GraphQL con sell-out + inventario.

Guarda el JSONL crudo en out/ y resume las claves de cada tipo de fila.
No toca la base de datos.

    python explore_data_kiosk.py [--days 7]
"""

import argparse
import json
from collections import Counter
from datetime import datetime

from config import settings
from spapi import data_kiosk
from spapi.client import SpApiClient, SpApiError, guardar_salida


def _resumen_jsonl(contenido: str) -> None:
    """El JSONL trae una fila por registro; se listan las claves vistas."""
    formas: Counter[tuple[str, ...]] = Counter()
    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            fila = json.loads(linea)
        except json.JSONDecodeError:
            continue
        if isinstance(fila, dict):
            formas[tuple(sorted(fila.keys()))] += 1
    for claves, cuantas in formas.most_common():
        print(f"  {cuantas:>6} filas con campos: {', '.join(claves)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba de Data Kiosk (GraphQL)")
    parser.add_argument("--days", type=int, default=None, help="dias hacia atras")
    parser.add_argument(
        "--print-query", action="store_true", help="solo imprime la query GraphQL"
    )
    parser.add_argument(
        "--solo-ventas",
        action="store_true",
        help="pide solo sell-out; permite el rango completo de --days. "
        "Sin esta bandera se piden ventas+inventario de UN solo dia, "
        "porque el inventario diario exige startDate == endDate.",
    )
    args = parser.parse_args()

    inicio, fin = settings.default_date_range(args.days)
    if not args.solo_ventas:
        # El inventario diario solo admite un dia; se usa el mas reciente.
        inicio = fin
    if args.print_query:
        print(
            data_kiosk.query_solo_ventas(inicio, fin)
            if args.solo_ventas
            else data_kiosk.query_sales_e_inventory(inicio, fin)
        )
        return 0

    client = SpApiClient()
    try:
        contenido = data_kiosk.ejecutar(
            client, inicio, fin, solo_ventas=args.solo_ventas
        )
    except (SpApiError, TimeoutError) as exc:
        print(f"  ERROR en Data Kiosk: {exc}")
        return 1
    if not contenido:
        return 0

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    guardar_salida(f"datakiosk_{sello}.jsonl", contenido)
    _resumen_jsonl(contenido)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
