"""Chequeo rapido: valida credenciales LWA y el acceso al endpoint.

    python check_auth.py
"""

from config import settings
from spapi.auth import LwaAuth
from spapi.client import SpApiClient, SpApiError


def main() -> int:
    faltantes = settings.missing_credentials()
    if faltantes:
        print("Faltan variables: " + ", ".join(faltantes))
        print("Copia .env.example a .env y completalo.")
        return 1

    token = LwaAuth().access_token()
    print(f"Access token OK (len={len(token)})")

    inicio, fin = settings.default_date_range()
    print(f"Endpoint       : {settings.ENDPOINT}")
    print(f"Marketplace    : {settings.MARKETPLACE_ID}")
    print(f"Rango de prueba: {inicio} -> {fin}")

    client = SpApiClient()
    try:
        # Listar reportes recientes es la llamada mas barata para confirmar
        # que la app tiene el rol y el marketplace correctos.
        respuesta = client.get_json(
            "/reports/2021-06-30/reports",
            params={
                "reportTypes": "GET_VENDOR_SALES_REPORT",
                "marketplaceIds": settings.MARKETPLACE_ID,
                "pageSize": 10,
            },
        )
    except SpApiError as exc:
        print(f"Reports API respondio con error: {exc}")
        return 1
    print(f"Reports API OK: {len(respuesta.get('reports', []))} reportes recientes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
