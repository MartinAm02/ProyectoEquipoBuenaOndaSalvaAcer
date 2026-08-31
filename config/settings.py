"""Configuracion del explorador SP-API.

Mismo patron que ACER Report Loader: se carga un .env sin dependencias
externas y las variables ya exportadas en la shell tienen prioridad.
"""

import os
from datetime import date, timedelta
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(env_path: Path) -> None:
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(BASE_DIR / ".env")

PROJECT_ROOT = BASE_DIR
OUTPUT_DIR = PROJECT_ROOT / "out"
LOG_DIR = PROJECT_ROOT / "logs"

LWA_CONFIG = {
    "client_id": os.environ.get("SPAPI_CLIENT_ID", ""),
    "client_secret": os.environ.get("SPAPI_CLIENT_SECRET", ""),
    "refresh_token": os.environ.get("SPAPI_REFRESH_TOKEN", ""),
    "token_url": os.environ.get(
        "SPAPI_LWA_ENDPOINT", "https://api.amazon.com/auth/o2/token"
    ),
}

ENDPOINT = os.environ.get("SPAPI_ENDPOINT", "https://sellingpartnerapi-na.amazon.com")
MARKETPLACE_ID = os.environ.get("SPAPI_MARKETPLACE_ID", "A1AM78C64UM0Y8")  # MX
TEST_DAYS_BACK = int(os.environ.get("SPAPI_TEST_DAYS_BACK", "7"))

# Data Kiosk publica los datos de un dia hasta ~34h despues, por eso el
# rango de prueba termina varios dias atras y no "ayer".
DATA_LAG_DAYS = 3


def default_date_range(days_back: int | None = None) -> tuple[date, date]:
    """Rango de fechas de prueba, ya descontando el lag de publicacion."""
    days_back = TEST_DAYS_BACK if days_back is None else days_back
    end = date.today() - timedelta(days=DATA_LAG_DAYS)
    start = end - timedelta(days=days_back - 1)
    return start, end


def missing_credentials() -> list[str]:
    """Nombres de las variables obligatorias que faltan en el entorno."""
    required = {
        "SPAPI_CLIENT_ID": LWA_CONFIG["client_id"],
        "SPAPI_CLIENT_SECRET": LWA_CONFIG["client_secret"],
        "SPAPI_REFRESH_TOKEN": LWA_CONFIG["refresh_token"],
    }
    return [name for name, value in required.items() if not value]
