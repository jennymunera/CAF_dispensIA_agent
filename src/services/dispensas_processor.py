import logging
from pathlib import Path
from typing import Any, Dict

from src.models.dispensa_task import DispensaTaskModel
from src.repositories.blob_storage_repository import BlobStorageRepository
from src.services.openai_http_client import OpenAIHttpClient
from src.utils.response_parser import parse_json_response

_LOGGER = logging.getLogger(__name__)


class DispensasProcessorService:
    def __init__(
        self,
        http_client: OpenAIHttpClient,
        blob_repository: BlobStorageRepository,
        base_path: str,
        results_folder: str,
    ) -> None:
        self._http_client = http_client
        self._blob_repository = blob_repository
        self._base_path = (base_path or "").strip("/")
        self._results_folder = (results_folder or "results").strip("/")

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

        chained_response = None
        parsed_json = parse_json_response(initial_response["content"])

        result = {
            "project_id": task.project_id,
            "document_name": task.document_name,
            "blob_url": task.blob_url,
            "initial_response": initial_response,
            "chained_response": chained_response,
            "parsed_json": parsed_json,
        }

        self._persist_result(task, parsed_json)

        _LOGGER.info(
            "Procesamiento de dispensa completado para el proyecto '%s' y documento '%s'",
            task.project_id,
            task.document_name,
        )
        return result

    def _persist_result(self, task: DispensaTaskModel, parsed_json: Any) -> None:
        blob_name = self._build_result_blob_name(task)
        try:
            self._blob_repository.upload_content_to_blob(
                content=parsed_json,
                blob_name=blob_name,
                indent_json=True,
            )
            _LOGGER.info(
                "Resultado JSON almacenado en '%s'",
                blob_name,
            )
        except Exception:
            _LOGGER.exception(
                "No se pudo almacenar el resultado JSON en Blob Storage para el documento '%s'",
                task.document_name,
            )
            raise

    def _build_result_blob_name(self, task: DispensaTaskModel) -> str:
        project_id = (task.project_id or "").strip("/")
        document_name = task.document_name or "resultado"
        stem = Path(document_name).stem or "resultado"

        parts = [self._base_path, project_id, self._results_folder, f"{stem}.json"]
        return "/".join(part for part in parts if part)
