"""Autenticacion LWA: intercambia el refresh token por un access token.

SP-API ya no exige firma SigV4 para llamadas normales; basta el header
`x-amz-access-token` con el access token de LWA.
"""

import time
from dataclasses import dataclass

import requests

from config import settings


@dataclass
class AccessToken:
    value: str
    expires_at: float

    @property
    def is_expired(self) -> bool:
        # Margen de 60s para no usar un token que caduca en pleno request.
        return time.time() >= self.expires_at - 60


class LwaAuth:
    def __init__(self, config: dict | None = None):
        self._config = config or settings.LWA_CONFIG
        self._token: AccessToken | None = None

    def access_token(self) -> str:
        if self._token is None or self._token.is_expired:
            self._token = self._request_token()
        return self._token.value

    def _request_token(self) -> AccessToken:
        faltantes = settings.missing_credentials()
        if faltantes:
            raise RuntimeError(
                "Faltan credenciales en el entorno: " + ", ".join(faltantes)
                + ". Copia .env.example a .env y completalo."
            )
        response = requests.post(
            self._config["token_url"],
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._config["refresh_token"],
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"LWA respondio {response.status_code}: {response.text[:500]}"
            )
        payload = response.json()
        return AccessToken(
            value=payload["access_token"],
            expires_at=time.time() + int(payload.get("expires_in", 3600)),
        )
