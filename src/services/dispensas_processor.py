import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set, List
import requests

from src.models.dispensa_task import DispensaTaskModel
from src.models.queue_message import QueueMessageModel
from src.repositories.blob_storage_repository import BlobStorageRepository
from src.services.notifications_service import NotificationsService
from src.services.blob_dispatcher import BlobDispatcherService
from src.services.service_bus_dispatcher import ServiceBusDispatcher
from src.services.openai_http_client import OpenAIHttpClient
from src.utils.build_email_payload import build_email_payload
from src.utils.response_parser import parse_json_response

_LOGGER = logging.getLogger(__name__)


class DispensasProcessorService:
    def __init__(
        self,
        http_client: OpenAIHttpClient,
        blob_repository: BlobStorageRepository,
        base_path: str,
        results_folder: str,
        notifications_service: Optional[NotificationsService] = None,
        sharepoint_folder: str = "",
        raw_folder: str = "raw",
        blob_dispatcher: Optional[BlobDispatcherService] = None,
        service_bus_dispatcher: Optional[ServiceBusDispatcher] = None,
    ) -> None:
        self._http_client = http_client
        self._blob_repository = blob_repository
        self._base_path = (base_path or "").strip("/")
        self._results_folder = (results_folder or "results").strip("/")
        self._notifications_service = notifications_service
        self._sharepoint_folder = sharepoint_folder
        self._raw_folder = (raw_folder or "raw").strip("/")
        self._info_start_notified: Set[str] = set()
        self._blob_dispatcher = blob_dispatcher
        self._service_bus_dispatcher = service_bus_dispatcher
        self._requeued_documents: Dict[str, Set[str]] = defaultdict(set)

    def process(self, task: DispensaTaskModel) -> Dict[str, Any]:
        _LOGGER.info(
            "Iniciando procesamiento de dispensa para el proyecto '%s' y documento '%s'",
            task.project_id,
            task.document_name,
        )
        self._maybe_notify_project_start(task.project_id)
        try:
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
        except Exception as exc:
            self._notify_error(task, exc)
            raise

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
            try:
                self._update_project_results_index(task)
            except Exception as exc:
                _LOGGER.exception(
                    "No se pudo actualizar el agregado de resultados para el proyecto '%s'",
                    task.project_id,
                )
                self._notify_error(task, exc)
            # Generar CSV sólo cuando el proyecto haya completado todo su procesamiento
            self._maybe_generate_csv(task)
        except Exception:
            _LOGGER.exception(
                "No se pudo almacenar el resultado JSON en Blob Storage para el documento '%s'",
                task.document_name,
            )
            raise

    def _build_result_blob_name(self, task: DispensaTaskModel) -> str:
        project_id = (task.project_id or "").strip("/")
        document_name = task.document_name or "resultado"
        # Normalizar stem para evitar duplicados por mayúsculas/espacios/variantes
        stem = Path(document_name).stem or "resultado"
        stem = stem.strip().lower().replace(" ", "_")

        parts = [
            self._base_path,
            project_id,
            self._results_folder,
            "dispensas",
            f"{stem}.json",
        ]
        return "/".join(part for part in parts if part)

    def _build_dispensas_prefix(self, task: DispensaTaskModel) -> str:
        project_id = (task.project_id or "").strip("/")
        parts = [self._base_path, project_id, self._results_folder, "dispensas"]
        return "/".join(part for part in parts if part)

    def _build_results_prefix(self, task: DispensaTaskModel) -> str:
        project_id = (task.project_id or "").strip("/")
        parts = [self._base_path, project_id, self._results_folder]
        return "/".join(part for part in parts if part)

    def _build_aggregate_blob_name(self, task: DispensaTaskModel) -> str:
        project_id = (task.project_id or "").strip("/")
        parts = [self._base_path, project_id, self._results_folder, "dispensas_results.json"]
        return "/".join(part for part in parts if part)

    def _build_info_start_marker(self, project_id: str) -> str:
        project = (project_id or "").strip("/")
        parts = [self._base_path, project, self._results_folder, ".info_start.sent"]
        return "/".join(part for part in parts if part)

    def _update_project_results_index(self, task: DispensaTaskModel) -> None:
        project_prefix = self._build_dispensas_prefix(task)
        if not project_prefix:
            _LOGGER.debug(
                "Prefijo de dispensas no disponible para el proyecto '%s'; se omite actualización",
                task.project_id,
            )
            return

        _LOGGER.info(
            "Iniciando actualización del índice agregado para el proyecto '%s' con prefijo '%s'",
            task.project_id,
            project_prefix,
        )

        container = self._blob_repository.default_container
        if not container:
            raise ValueError("No se configuró el contenedor por defecto de Blob Storage")

        prefix_for_listing = f"{project_prefix.rstrip('/')}/"
        _LOGGER.info(
            "Listando blobs con prefijo '%s' en contenedor '%s'",
            prefix_for_listing,
            container,
        )
        
        blob_names = self._blob_repository.list_blobs(
            prefix=prefix_for_listing,
            container_name=container,
        )
        blob_names = sorted(blob_names)
        
        _LOGGER.info(
            "Encontrados %d blobs para el proyecto '%s': %s",
            len(blob_names),
            task.project_id,
            blob_names,
        )

        # Usar un mapa por stem para evitar duplicados en el agregado
        aggregated_map = {}
        for blob_name in blob_names:
            # Filtrar solo archivos .json individuales, no el archivo agregado
            if blob_name.endswith("dispensas_results.json"):
                _LOGGER.debug("Omitiendo archivo agregado: %s", blob_name)
                continue
            
            # Solo procesar archivos .json individuales
            if not blob_name.endswith(".json"):
                _LOGGER.debug("Omitiendo archivo que no es .json: %s", blob_name)
                continue
                
            _LOGGER.info("Procesando blob individual: %s", blob_name)
            try:
                raw_bytes = self._blob_repository.read_item_from_blob(
                    blob_name,
                    container_name=container,
                )
                decoded = raw_bytes.decode("utf-8")
                parsed_content = json.loads(decoded)
                normalized_stem = Path(blob_name).stem.strip().lower().replace(" ", "_")
                aggregated_map[normalized_stem] = parsed_content
                _LOGGER.info(
                    "Agregado exitosamente el contenido del blob '%s' (tamaño: %d bytes)",
                    blob_name,
                    len(raw_bytes),
                )
            except json.JSONDecodeError:
                _LOGGER.exception(
                    "Error al parsear JSON del blob '%s' - contenido no válido",
                    blob_name,
                )
            except Exception:
                _LOGGER.exception(
                    "No se pudo agregar el resultado del blob '%s' al agregado del proyecto '%s'",
                    blob_name,
                    task.project_id,
                )

        aggregated_items = list(aggregated_map.values())
        _LOGGER.info(
            "Total de elementos únicos tras deduplicación: %d (de %d blobs)",
            len(aggregated_items),
            len(blob_names),
        )

        aggregate_blob_name = self._build_aggregate_blob_name(task)
        _LOGGER.info(
            "Guardando archivo agregado en '%s' con %d elementos",
            aggregate_blob_name,
            len(aggregated_items),
        )
        
        self._blob_repository.upload_content_to_blob(
            content=aggregated_items,
            blob_name=aggregate_blob_name,
            indent_json=True,
        )
        _LOGGER.info(
            "Archivo agregado actualizado exitosamente en '%s' con %d elementos",
            aggregate_blob_name,
            len(aggregated_items),
        )

    # --- Helpers para disparo condicional de CSV ---
    def _normalize_stem(self, name: str) -> str:
        return Path(name).stem.strip().lower().replace(" ", "_")

    def _build_raw_prefix(self, task: DispensaTaskModel) -> str:
        project_id = (task.project_id or "").strip("/")
        parts = [self._base_path, project_id, self._raw_folder]
        return "/".join(part for part in parts if part)

    def _list_normalized_stems(self, prefix: str, only_suffix: Optional[str] = None) -> Set[str]:
        try:
            container = self._blob_repository.default_container
            blob_names = self._blob_repository.list_blobs(prefix=f"{prefix.rstrip('/')}/", container_name=container)
            stems: Set[str] = set()
            for bn in blob_names:
                if only_suffix and not bn.endswith(only_suffix):
                    continue
                stems.add(self._normalize_stem(bn))
            return stems
        except Exception:
            _LOGGER.exception("Error listando blobs para prefijo '%s'", prefix)
            return set()

    def _is_project_processing_complete(self, task: DispensaTaskModel) -> bool:
        raw_prefix = self._build_raw_prefix(task)
        results_prefix = self._build_dispensas_prefix(task)
        self._normalize_results_location(task)
        raw_stems = self._list_normalized_stems(raw_prefix)
        result_stems = self._list_normalized_stems(results_prefix, only_suffix=".json")
        if not raw_stems:
            return False
        missing = raw_stems - result_stems
        _LOGGER.info(
            "Progreso proyecto '%s': raw=%d, results=%d, pendientes=%d",
            task.project_id,
            len(raw_stems),
            len(result_stems),
            len(missing),
        )
        if missing:
            self._requeue_missing_documents(task, missing)
        return len(missing) == 0

    def _blob_exists(self, blob_name: str) -> bool:
        try:
            container = self._blob_repository.default_container
            names = self._blob_repository.list_blobs(prefix=blob_name, container_name=container)
            return blob_name in names
        except Exception:
            return False

    def _remove_blob_safely(self, blob_name: str) -> None:
        try:
            self._blob_repository.delete_blob(blob_name)
        except Exception:
            _LOGGER.debug("No se pudo eliminar el blob '%s' (posiblemente no existe)", blob_name)

    def _normalize_results_location(self, task: DispensaTaskModel) -> None:
        container = self._blob_repository.default_container
        if not container:
            return

        results_prefix = self._build_results_prefix(task)
        dispensas_prefix = self._build_dispensas_prefix(task)
        if not results_prefix or not dispensas_prefix:
            return

        try:
            blobs = self._blob_repository.list_blobs(
                prefix=f"{results_prefix.rstrip('/')}/",
                container_name=container,
            )
        except Exception:
            _LOGGER.exception(
                "No se pudo listar blobs para normalizar resultados del proyecto '%s'",
                task.project_id,
            )
            return

        dispensas_segment = f"/{self._results_folder}/dispensas/"
        for blob_name in blobs:
            if not blob_name.endswith(".json"):
                continue
            if blob_name.endswith("dispensas_results.json"):
                continue
            if dispensas_segment in blob_name:
                continue

            filename = Path(blob_name).name
            target_blob = f"{dispensas_prefix.rstrip('/')}/{filename}"
            _LOGGER.info(
                "Reubicando resultado de '%s' a '%s' para el proyecto '%s'",
                blob_name,
                target_blob,
                task.project_id,
            )
            try:
                raw_bytes = self._blob_repository.read_item_from_blob(blob_name, container_name=container)
                self._blob_repository.upload_bytes_to_blob(
                    raw_bytes,
                    blob_name=target_blob,
                    container_name=container,
                    content_type="application/json",
                )
                self._blob_repository.delete_blob(blob_name, container_name=container)
            except Exception:
                _LOGGER.exception(
                    "No se pudo mover el blob '%s' al directorio de dispensas para el proyecto '%s'",
                    blob_name,
                    task.project_id,
                )

    def _requeue_missing_documents(self, task: DispensaTaskModel, missing_stems: Set[str]) -> None:
        if not self._blob_dispatcher or not self._service_bus_dispatcher:
            return

        project_id = (task.project_id or "").strip("/")
        if not project_id:
            return

        already_requeued = self._requeued_documents[project_id]
        stems_to_requeue = [stem for stem in missing_stems if stem not in already_requeued]
        if not stems_to_requeue:
            return

        raw_prefix = self._build_raw_prefix(task)
        container = self._blob_repository.default_container
        try:
            raw_blobs = self._blob_repository.list_blobs(
                prefix=f"{raw_prefix.rstrip('/')}/",
                container_name=container,
            )
        except Exception:
            _LOGGER.exception(
                "No se pudo listar blobs raw para reencolar pendientes del proyecto '%s'",
                project_id,
            )
            return

        stem_to_blob: Dict[str, str] = {}
        for blob_name in raw_blobs:
            normalized = self._normalize_stem(blob_name)
            stem_to_blob[normalized] = blob_name

        documents_to_dispatch: List[str] = []
        for stem in stems_to_requeue:
            blob_name = stem_to_blob.get(stem)
            if blob_name:
                documents_to_dispatch.append(blob_name)
            else:
                _LOGGER.warning(
                    "No se encontró blob raw para el documento pendiente '%s' del proyecto '%s'",
                    stem,
                    project_id,
                )

        if not documents_to_dispatch:
            return

        payload = {
            "project_id": project_id,
            "trigger_type": "document",
            "documents": documents_to_dispatch,
            "model": task.model,
            "chained_prompt": task.chained_prompt,
        }

        try:
            queue_message = QueueMessageModel.from_dict(payload)
            tasks = self._blob_dispatcher.generate_tasks(queue_message)
            if tasks:
                sent = self._service_bus_dispatcher.send_tasks(tasks)
                if sent:
                    already_requeued.update(stems_to_requeue)
                    _LOGGER.info(
                        "Se reencolaron %s documentos pendientes para el proyecto '%s': %s",
                        sent,
                        project_id,
                        documents_to_dispatch,
                    )
        except Exception:
            _LOGGER.exception(
                "No se pudieron reencolar documentos pendientes para el proyecto '%s'",
                project_id,
            )

    def _maybe_generate_csv(self, task: DispensaTaskModel) -> None:
        project_id = (task.project_id or "").strip("/")
        lock_blob = f"{self._base_path}/{project_id}/{self._results_folder}/.csv_generation.lock"
        done_blob = f"{self._base_path}/{project_id}/{self._results_folder}/csv_generation.done"

        if self._blob_exists(done_blob):
            _LOGGER.info("CSV ya generado previamente para el proyecto '%s'", project_id)
            return

        if not self._is_project_processing_complete(task):
            _LOGGER.debug("Aún no se completa el procesamiento para el proyecto '%s'", project_id)
            return

        if self._blob_exists(lock_blob):
            _LOGGER.info("Generación de CSV en curso para el proyecto '%s'", project_id)
            return

        # Crear lock
        lock_created = False
        try:
            self._blob_repository.upload_content_to_blob(
                content={"status": "locked"},
                blob_name=lock_blob,
                indent_json=True,
            )
            lock_created = True
        except Exception:
            _LOGGER.exception("No se pudo crear el lock de CSV para el proyecto '%s'", project_id)
            return

        payload = {"project_id": project_id}
        try:
            base_url = os.environ.get("INTERNAL_API_BASE_URL", "http://127.0.0.1:7071/api").rstrip("/")
            response = requests.post(
                f"{base_url}/json_to_csv_request",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=180,
            )
            if response.status_code == 200:
                _LOGGER.info("CSV generado exitosamente para el proyecto '%s'", project_id)
                self._notify_csv_success(project_id)
                try:
                    self._blob_repository.upload_content_to_blob(
                        content={"status": "done"},
                        blob_name=done_blob,
                        indent_json=True,
                    )
                except Exception:
                    _LOGGER.warning("No se pudo crear el marcador de finalización CSV para '%s'", project_id)
                finally:
                    if lock_created:
                        self._remove_blob_safely(lock_blob)
            else:
                _LOGGER.warning(
                    "Error al generar CSV para el proyecto '%s': %s",
                    project_id,
                    response.text,
                )
                # Enviar notificación de error de CSV
                self._notify_csv_error(project_id, response.text)
                if lock_created:
                    self._remove_blob_safely(lock_blob)
        except Exception as csv_exc:
            _LOGGER.exception(
                "Error al llamar a json_to_csv_request para el proyecto '%s': %s",
                project_id,
                csv_exc,
            )
            # Enviar notificación de error de CSV por excepción
            self._notify_csv_error(project_id, str(csv_exc))
            if lock_created:
                self._remove_blob_safely(lock_blob)

    def notify_process_completed(self, project_id: str, suffix: str = "") -> None:
        """Envía la notificación de finalización del proceso para el proyecto completo."""
        if not self._notifications_service:
            return

        process_name = project_id.strip()
        if suffix:
            process_name = f"{process_name} | {suffix.strip()}"

        self._send_notification("SUCCESS_FINALLY_PROCESS", process_name)

    def _notify_error(self, task: DispensaTaskModel, exc: Exception) -> None:
        if not self._notifications_service:
            return

        process_name = f"{task.project_id} | {task.document_name}"
        try:
            payload = build_email_payload("ERROR_FINALLY_PROCESS", process_name, self._sharepoint_folder)
            payload["data"].append({"label": "{{error}}", "value": str(exc)})
            self._notifications_service.send(payload)
            _LOGGER.info(
                "Notificación de error enviada para el proyecto '%s', documento '%s'",
                task.project_id,
                task.document_name,
            )
        except Exception:
            _LOGGER.exception(
                "No se pudo enviar la notificación de error para el proyecto '%s', documento '%s'",
                task.project_id,
                task.document_name,
            )

    def _notify_csv_success(self, project_id: str) -> None:
        """Envía notificación de éxito cuando se genera el CSV para un proyecto."""
        if not self._notifications_service:
            return
        process_name = f"{project_id} | CSV Generado"
        try:
            payload = build_email_payload("SUCCESS_FINALLY_PROCESS", process_name, self._sharepoint_folder)
            self._notifications_service.send(payload)
            _LOGGER.info("Notificación de éxito CSV enviada para el proyecto '%s'", project_id)
        except Exception:
            _LOGGER.exception("No se pudo enviar la notificación de éxito CSV para el proyecto '%s'", project_id)

    def _notify_csv_error(self, project_id: str, details: str) -> None:
        """Envía notificación de error cuando falla la generación de CSV para un proyecto."""
        if not self._notifications_service:
            return

        process_name = f"{project_id} | CSV Error"
        try:
            # Según política: ERROR_FINALLY_PROCESS también cuando no se genera el CSV
            payload = build_email_payload("ERROR_FINALLY_PROCESS", process_name, self._sharepoint_folder)
            payload["data"].append({"label": "{{error}}", "value": details})
            self._notifications_service.send(payload)
            _LOGGER.info("Notificación de error CSV enviada para el proyecto '%s'", project_id)
        except Exception:
            _LOGGER.exception(
                "No se pudo enviar la notificación de error CSV para el proyecto '%s'",
                project_id,
            )

    def _notify_info_start(self, project_id: str) -> None:
        """Envía notificación de inicio de proceso (INFO_START_PROCESS) para el proyecto."""
        if not self._notifications_service:
            return
        process_name = project_id.strip()
        payload = build_email_payload("INFO_START_PROCESS", process_name, self._sharepoint_folder)
        response = self._notifications_service.send(payload)
        status = getattr(response, "status_code", None)
        if status and status >= 400:
            raise RuntimeError(f"Fallo el envío de INFO_START_PROCESS (status {status})")
        _LOGGER.info("Notificación de inicio enviada para el proyecto '%s'", project_id)

    def _send_notification(self, notification_type: str, process_name: str) -> None:
        if not self._notifications_service:
            return

        try:
            payload = build_email_payload(notification_type, process_name, self._sharepoint_folder)
            self._notifications_service.send(payload)
        except Exception:
            _LOGGER.exception("No se pudo enviar la notificación '%s'", notification_type)

    def _maybe_notify_project_start(self, project_id: str) -> None:
        if not self._notifications_service:
            return

        normalized = (project_id or "").strip()
        if not normalized:
            return

        if normalized in self._info_start_notified:
            return

        marker_blob = self._build_info_start_marker(normalized)
        if self._blob_exists(marker_blob):
            self._info_start_notified.add(normalized)
            return

        try:
            self._notify_info_start(normalized)
        except Exception:
            _LOGGER.exception("No se pudo enviar INFO_START_PROCESS para el proyecto '%s'", normalized)
            return

        self._info_start_notified.add(normalized)

        try:
            self._blob_repository.upload_content_to_blob(
                content={
                    "status": "sent",
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                },
                blob_name=marker_blob,
                indent_json=True,
            )
        except Exception:
            _LOGGER.warning(
                "No se pudo registrar el marcador de inicio para el proyecto '%s'",
                normalized,
            )
