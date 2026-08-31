"""Cliente HTTP minimo para SP-API con backoff ante 429/5xx."""

import json
import random
import time
from pathlib import Path

import requests

from config import settings
from spapi.auth import LwaAuth


MAX_RETRIES = 6


class SpApiError(RuntimeError):
    def __init__(self, status_code: int, body: str):
        super().__init__(f"SP-API respondio {status_code}: {body[:800]}")
        self.status_code = status_code
        self.body = body


class SpApiClient:
    def __init__(self, endpoint: str | None = None, auth: LwaAuth | None = None):
        self.endpoint = (endpoint or settings.ENDPOINT).rstrip("/")
        self.auth = auth or LwaAuth()
        self.session = requests.Session()

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Llama a SP-API reintentando con backoff exponencial ante 429/5xx.

        Los rate limits de SP-API son un token bucket por operacion, asi que
        el 429 es esperable y no un error: se respeta y se reintenta.
        """
        url = path if path.startswith("http") else f"{self.endpoint}{path}"
        for intento in range(MAX_RETRIES):
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("x-amz-access-token", self.auth.access_token())
            headers.setdefault("content-type", "application/json")
            response = self.session.request(
                method, url, headers=headers, timeout=60, **kwargs
            )
            if response.status_code == 429 or response.status_code >= 500:
                if intento == MAX_RETRIES - 1:
                    break
                espera = (2 ** intento) + random.uniform(0, 1)
                print(
                    f"  [{response.status_code}] backoff {espera:.1f}s "
                    f"(intento {intento + 1}/{MAX_RETRIES})"
                )
                time.sleep(espera)
                continue
            return response
        raise SpApiError(response.status_code, response.text)

    def get_json(self, path: str, params: dict | None = None) -> dict:
        response = self.request("GET", path, params=params)
        if response.status_code >= 400:
            raise SpApiError(response.status_code, response.text)
        return response.json()

    def post_json(self, path: str, payload: dict) -> dict:
        response = self.request("POST", path, data=json.dumps(payload))
        if response.status_code >= 400:
            raise SpApiError(response.status_code, response.text)
        return response.json()

    def download(self, url: str) -> bytes:
        """Descarga un documento de reporte/kiosk (URL prefirmada, sin token)."""
        response = self.session.get(url, timeout=300)
        response.raise_for_status()
        return response.content


def guardar_salida(nombre: str, contenido: bytes | str) -> Path:
    """Guarda output crudo en out/ para inspeccion manual."""
    settings.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    destino = settings.OUTPUT_DIR / nombre
    modo = "wb" if isinstance(contenido, bytes) else "w"
    with open(destino, modo, encoding=None if isinstance(contenido, bytes) else "utf-8") as fh:
        fh.write(contenido)
    print(f"  -> guardado en {destino}")
    return destino
