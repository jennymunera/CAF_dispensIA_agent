import json
import logging
from typing import Any, Dict, Optional

import requests

_LOGGER = logging.getLogger(__name__)


class OpenAIHttpClient:
    def __init__(
        self,
        base_url: str,
        function_key: Optional[str] = None,
        timeout: int = 120,
    ) -> None:
        if not base_url:
            raise ValueError("La URL base del API interno es obligatoria")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._function_key = function_key
        self._session = requests.Session()

    def _build_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._function_key:
            headers["x-functions-key"] = self._function_key
        return headers

    def _post(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self._base_url}/{endpoint.lstrip('/') }"
        try:
            response = self._session.post(
                url,
                headers=self._build_headers(),
                data=json.dumps(payload, ensure_ascii=False),
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            _LOGGER.error("No se pudo contactar el endpoint interno '%s': %s", url, exc)
            raise ValueError("Error de comunicación con el API interno") from exc

        if response.status_code >= 400:
            _LOGGER.error(
                "El endpoint interno '%s' respondió con error %s: %s",
                url,
                response.status_code,
                response.text,
            )
            raise ValueError(
                f"El API interno devolvió un error ({response.status_code})"
            )

        try:
            return response.json()
        except ValueError as exc:
            _LOGGER.error("La respuesta del endpoint interno '%s' no es JSON válido", url)
            raise ValueError("La respuesta del API interno no es JSON válido") from exc

    def request_with_file(self, blob_url: str, prompt: str, model: str) -> Dict[str, Any]:
        payload = {
            "blob_url": blob_url,
            "prompt": prompt,
            "model": model,
        }
        return self._post("request-with-file", payload)

    def chained_request(self, model: str, prompt: str, previous_response_id: str) -> Dict[str, Any]:
        payload = {
            "model": model,
            "prompt": prompt,
            "previous_response_id": previous_response_id,
        }
        return self._post("chained-request", payload)
