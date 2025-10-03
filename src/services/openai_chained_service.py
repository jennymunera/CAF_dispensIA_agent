import logging
from typing import Dict

from src.services.openai_client_factory import OpenAIClientFactory
from src.utils.response_parser import extract_response_text

_LOGGER = logging.getLogger(__name__)


class OpenAIChainedService:
    def __init__(self, client_factory: OpenAIClientFactory) -> None:
        self._client_factory = client_factory

    def send_chained_request(self, model: str, prompt: str, previous_response_id: str) -> Dict[str, str]:
        if not model:
            raise ValueError("El modelo de OpenAI es obligatorio para la solicitud encadenada")
        if not prompt:
            raise ValueError("El prompt encadenado es obligatorio")
        if not previous_response_id:
            raise ValueError("El identificador de la respuesta previa es obligatorio")

        client = self._client_factory.create_client()
        try:
            response = client.responses.create(
                model=model,
                input=[{"role": "user", "content": prompt}],
                extra_body={"previous_response_id": previous_response_id},
            )
            content = extract_response_text(response)
            return {"response_id": response.id, "content": content}
        except Exception:
            _LOGGER.exception("Error al realizar la solicitud encadenada con response_id previo '%s'", previous_response_id)
            raise
