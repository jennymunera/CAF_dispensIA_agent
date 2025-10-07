import logging
from datetime import datetime, timezone
from typing import List, Optional

from pathlib import Path, PurePosixPath

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
        base_path: str = "",
        raw_folder: str = "raw",
    ) -> None:
        self._blob_repository = blob_repository
        self._default_model = default_model
        self._default_agent_prompt = default_agent_prompt
        self._default_chained_prompt = default_chained_prompt
        self._base_path = (base_path or "").strip("/")
        self._raw_folder = (raw_folder or "raw").strip("/")
        self._unified_prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "agente_unificado.txt"
        self._unified_prompt_cache: Optional[str] = None

    def generate_tasks(self, message: QueueMessageModel) -> List[DispensaTaskModel]:
        trigger_type = message.trigger_type.lower()
        model = message.model or self._default_model
        prompt_template = self._load_unified_prompt()
        chained_prompt = message.chained_prompt or self._default_chained_prompt
        project_key = self._normalize_project_id(message.project_id)
        extraction_timestamp = datetime.now(timezone.utc).isoformat()

        if not model:
            raise ValueError("No se definió el modelo a utilizar para el procesamiento")
        if not prompt_template:
            raise ValueError("No se pudo cargar el prompt unificado del agente")
        if not chained_prompt:
            raise ValueError("No se definió el prompt encadenado")

        container = self._blob_repository.default_container
        if not container:
            raise ValueError("No se configuró el contenedor por defecto de Blob Storage")

        raw_prefix = self._build_raw_prefix(project_key)

        if trigger_type == "project":
            blob_names = self._blob_repository.list_blobs(prefix=f"{raw_prefix}", container_name=container)
            if not blob_names:
                raise ValueError(
                    "No se encontraron documentos para el proyecto especificado"
                )
        elif trigger_type == "document":
            message.require_documents()
            blob_names = [
                self._resolve_blob_name(project_key, doc)
                for doc in message.documents
            ]
        else:
            raise ValueError(f"El tipo de disparo '{message.trigger_type}' no es soportado")

        tasks: List[DispensaTaskModel] = []
        for blob_name in blob_names:
            blob_url = self._build_blob_url(container, blob_name)
            document_name = blob_name.split("/")[-1]
            agent_prompt = self._build_agent_prompt(
                template=prompt_template,
                project_key=project_key,
                extraction_timestamp=extraction_timestamp,
                document_name=document_name,
            )
            tasks.append(
                DispensaTaskModel(
                    project_id=project_key,
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
        normalized_document = document.replace("\\", "/").strip("/")

        full_raw_prefix = self._build_path(project_id, self._raw_folder)
        if normalized_document.startswith(full_raw_prefix):
            return normalized_document

        if normalized_document.startswith(self._base_path):
            return normalized_document

        relative = normalized_document

        if normalized_document.startswith(project_id):
            relative = normalized_document[len(project_id):].lstrip("/")

        if relative.startswith(self._raw_folder):
            relative = relative[len(self._raw_folder):].lstrip("/")

        return self._build_path(project_id, self._raw_folder, relative)

    def _build_blob_url(self, container: str, blob_name: str) -> str:
        endpoint = self._blob_repository.blob_service_client.primary_endpoint.rstrip("/")
        return f"{endpoint}/{container}/{blob_name}"

    def _build_raw_prefix(self, project_id: str) -> str:
        base_path = self._build_path(project_id, self._raw_folder)
        return f"{base_path}/"

    def _build_path(self, project_id: str, *extra: str) -> str:
        path = PurePosixPath()
        for part in (self._base_path, project_id, *extra):
            if part:
                path = path.joinpath(part.strip("/"))
        return str(path)

    def _normalize_project_id(self, project_id: str) -> str:
        project_id = (project_id or "").strip("/")

        if self._base_path and project_id.startswith(f"{self._base_path}/"):
            project_id = project_id[len(self._base_path):].lstrip("/")

        if project_id.endswith(f"/{self._raw_folder}"):
            project_id = project_id[: -len(self._raw_folder) - 1]

        return project_id

    def _load_unified_prompt(self) -> str:
        if self._unified_prompt_cache is not None:
            return self._unified_prompt_cache

        try:
            prompt = self._unified_prompt_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise ValueError(
                "No se encontró el archivo de prompt unificado en 'src/prompts/agente_unificado.txt'"
            ) from exc

        if not prompt:
            raise ValueError("El prompt unificado está vacío")

        self._unified_prompt_cache = prompt
        return prompt

    def _build_agent_prompt(
        self,
        template: str,
        project_key: str,
        extraction_timestamp: str,
        document_name: str,
    ) -> str:
        dynamic_block = (
            "\n\n[Contexto de ejecución]\n"
            f"- Proyecto CAF: {project_key}\n"
            f"- Fecha de extracción (UTC): {extraction_timestamp}\n"
            f"- Archivo procesado: {document_name}\n"
        )
        return f"{template}{dynamic_block}"
