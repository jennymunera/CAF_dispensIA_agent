import logging
from typing import Any, Dict

from src.models.dispensa_task import DispensaTaskModel
from src.services.openai_chained_service import OpenAIChainedService
from src.services.openai_file_service import OpenAIFileService
from src.utils.response_parser import parse_json_response

_LOGGER = logging.getLogger(__name__)


class DispensasProcessorService:
    def __init__(
        self,
        file_service: OpenAIFileService,
        chained_service: OpenAIChainedService,
    ) -> None:
        self._file_service = file_service
        self._chained_service = chained_service

    def process(self, task: DispensaTaskModel) -> Dict[str, Any]:
        _LOGGER.info(
            "Iniciando procesamiento de dispensa para el proyecto '%s' y documento '%s'",
            task.project_id,
            task.document_name,
        )

        initial_response = self._file_service.send_request_with_file(
            blob_url=task.blob_url,
            prompt=task.agent_prompt,
            model=task.model,
        )

        chained_response = self._chained_service.send_chained_request(
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
