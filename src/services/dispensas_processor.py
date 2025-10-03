import logging
from typing import Any, Dict

from src.models.dispensa_task import DispensaTaskModel
from src.services.openai_http_client import OpenAIHttpClient
from src.utils.response_parser import parse_json_response

_LOGGER = logging.getLogger(__name__)


class DispensasProcessorService:
    def __init__(
        self,
        http_client: OpenAIHttpClient,
    ) -> None:
        self._http_client = http_client

    def process(self, task: DispensaTaskModel) -> Dict[str, Any]:
        _LOGGER.info(
            "Iniciando procesamiento de dispensa para el proyecto '%s' y documento '%s'",
            task.project_id,
            task.document_name,
        )

        initial_response = self._http_client.request_with_file(
            blob_url=task.blob_url,
            prompt=task.agent_prompt,
            model=task.model,
        )

        chained_response = self._http_client.chained_request(
            model=task.model,
            prompt=task.chained_prompt,
            previous_response_id=initial_response["response_id"],
        )

        parsed_json = parse_json_response(chained_response["content"])

        result = {
            "project_id": task.project_id,
            "document_name": task.document_name,
            "blob_url": task.blob_url,
            "initial_response": initial_response,
            "chained_response": chained_response,
            "parsed_json": parsed_json,
        }

        _LOGGER.info(
            "Procesamiento de dispensa completado para el proyecto '%s' y documento '%s'",
            task.project_id,
            task.document_name,
        )
        return result
