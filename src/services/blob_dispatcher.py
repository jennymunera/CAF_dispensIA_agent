import logging
from typing import List, Optional

from src.models.dispensa_task import DispensaTaskModel
from src.models.queue_message import QueueMessageModel
from src.repositories.blob_storage_repository import BlobStorageRepository

_LOGGER = logging.getLogger(__name__)


class BlobDispatcherService:
    def __init__(
        self,
        blob_repository: BlobStorageRepository,
        default_model: Optional[str] = None,
        default_agent_prompt: Optional[str] = None,
        default_chained_prompt: Optional[str] = None,
    ) -> None:
        self._blob_repository = blob_repository
        self._default_model = default_model
        self._default_agent_prompt = default_agent_prompt
        self._default_chained_prompt = default_chained_prompt

    def generate_tasks(self, message: QueueMessageModel) -> List[DispensaTaskModel]:
        trigger_type = message.trigger_type.lower()
        model = message.model or self._default_model
        agent_prompt = message.agent_prompt or self._default_agent_prompt
        chained_prompt = message.chained_prompt or self._default_chained_prompt

        if not model:
            raise ValueError("No se definió el modelo a utilizar para el procesamiento")
        if not agent_prompt:
            raise ValueError("No se definió el prompt del agente")
        if not chained_prompt:
            raise ValueError("No se definió el prompt encadenado")

        container = self._blob_repository.default_container
        if not container:
            raise ValueError("No se configuró el contenedor por defecto de Blob Storage")

        if trigger_type == "project":
            prefix = f"{message.project_id}/"
            blob_names = self._blob_repository.list_blobs(prefix=prefix, container_name=container)
            if not blob_names:
                raise ValueError(
                    "No se encontraron documentos para el proyecto especificado"
                )
        elif trigger_type == "document":
            message.require_documents()
            blob_names = [self._resolve_blob_name(message.project_id, doc) for doc in message.documents]
        else:
            raise ValueError(f"El tipo de disparo '{message.trigger_type}' no es soportado")

        tasks: List[DispensaTaskModel] = []
        for blob_name in blob_names:
            blob_url = self._build_blob_url(container, blob_name)
            document_name = blob_name.split("/")[-1]
            tasks.append(
                DispensaTaskModel(
                    project_id=message.project_id,
                    blob_url=blob_url,
                    model=model,
                    agent_prompt=agent_prompt,
                    chained_prompt=chained_prompt,
                    document_name=document_name,
                )
            )
            _LOGGER.info(
                "Se generó una tarea para el documento '%s' del proyecto '%s'",
                blob_name,
                message.project_id,
            )

        return tasks

    def _resolve_blob_name(self, project_id: str, document: str) -> str:
        document = document.strip()
        if not document:
            raise ValueError("Se incluyó un nombre de documento vacío en la solicitud")
        if document.startswith(f"{project_id}/"):
            return document
        return f"{project_id}/{document}"

    def _build_blob_url(self, container: str, blob_name: str) -> str:
        endpoint = self._blob_repository.blob_service_client.primary_endpoint.rstrip("/")
        return f"{endpoint}/{container}/{blob_name}"
