import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from src.interfaces.blob_storage_interface import BlobStorageInterface
from src.services.openai_client_factory import OpenAIClientFactory
from src.utils.blob_url_parser import parse_blob_url
from src.utils.content_type import guess_filename_and_content_type
from src.utils.response_parser import extract_response_text

_LOGGER = logging.getLogger(__name__)


class OpenAIFileService:
    def __init__(self, blob_repository: BlobStorageInterface, client_factory: OpenAIClientFactory) -> None:
        self._blob_repository = blob_repository
        self._client_factory = client_factory

    def send_request_with_file(self, blob_url: str, prompt: str, model: str) -> Dict[str, str]:
        if not prompt:
            raise ValueError("El prompt del agente es obligatorio para la solicitud con archivo")
        if not model:
            raise ValueError("El modelo de OpenAI es obligatorio para la solicitud con archivo")

        container_name, blob_name = parse_blob_url(blob_url)
        _LOGGER.info("Descargando blob '%s' del contenedor '%s'", blob_name, container_name)
        blob_bytes = self._blob_repository.read_item_from_blob(blob_name=blob_name, container_name=container_name)

        filename, _ = guess_filename_and_content_type(blob_name)
        suffix = os.path.splitext(filename)[1] or ".tmp"

        client = self._client_factory.create_client()
        temp_file_path = ""
        uploaded_file_id = None
        upload_attempts = 3
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(blob_bytes)
                temp_file_path = temp_file.name

            for attempt in range(1, upload_attempts + 1):
                try:
                    with open(temp_file_path, "rb") as file_handle:
                        uploaded_file = client.files.create(file=file_handle, purpose="assistants")
                        uploaded_file_id = uploaded_file.id
                    break
                except Exception as upload_exc:
                    if attempt >= upload_attempts:
                        _LOGGER.error(
                            "Falló la subida del archivo a OpenAI tras %s intentos para '%s'",
                            upload_attempts,
                            blob_name,
                        )
                        raise upload_exc
                    wait_time = min(2 * attempt, 10)
                    _LOGGER.warning(
                        "Error subiendo archivo a OpenAI (intento %s/%s) para '%s'. Reintentando en %s segundos",
                        attempt,
                        upload_attempts,
                        blob_name,
                        wait_time,
                    )
                    time.sleep(wait_time)

            response = client.responses.create(
                model=model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": prompt},
                            {"type": "input_file", "file_id": uploaded_file_id},
                        ],
                    }
                ],
            )

            content = extract_response_text(response)
            result = {"response_id": response.id, "content": content}

            if self._should_retry_with_images(content):
                _LOGGER.info(
                    "El contenido generado está vacío para '%s'; intentando fallback con modelo de visión",
                    blob_name,
                )
                try:
                    vision_result = self._try_with_images(blob_bytes, prompt)
                except Exception:
                    _LOGGER.exception(
                        "Falló el fallback con modelo de visión para el blob '%s'",
                        blob_name,
                    )
                    vision_result = None
                if vision_result:
                    result = vision_result

            try:
                self._persist_processed_result(container_name, blob_name, result)
            except Exception:
                _LOGGER.exception(
                    "No se pudo almacenar el resultado procesado en processed/ para '%s'",
                    blob_name,
                )

            return result
        except Exception as exc:
            _LOGGER.exception("Error al procesar la solicitud con archivo para el blob '%s'", blob_name)
            if uploaded_file_id:
                try:
                    client.files.delete(uploaded_file_id)
                except Exception:
                    _LOGGER.warning(
                        "No se pudo eliminar el archivo temporal de OpenAI con id '%s'", uploaded_file_id
                    )
                uploaded_file_id = None
            if str(exc).lower().startswith("error code: 500"):
                _LOGGER.info(
                    "Fallo subida de archivo para '%s' con error 500; intentando fallback con modelo de visión",
                    blob_name,
                )
                vision_result = None
                try:
                    vision_result = self._try_with_images(blob_bytes, prompt)
                except Exception:
                    _LOGGER.exception(
                        "Falló el fallback con modelo de visión tras error 500 para '%s'",
                        blob_name,
                    )
                if vision_result:
                    return vision_result
            raise
        finally:
            if uploaded_file_id:
                try:
                    client.files.delete(uploaded_file_id)
                except Exception:
                    _LOGGER.warning(
                        "No se pudo eliminar el archivo temporal de OpenAI con id '%s'", uploaded_file_id
                    )
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    _LOGGER.warning("No se pudo eliminar el archivo temporal '%s'", temp_file_path)

    def _should_retry_with_images(self, content: str) -> bool:
        if not content or not content.strip():
            return True
        normalized = content.lower()
        failure_markers = (
            "no pude leer",
            "no se pudo leer",
            "no he podido leer",
            "no content",
            "could not read",
            "no text",
        )
        if any(marker in normalized for marker in failure_markers):
            return True

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return False
        if isinstance(parsed, dict):
            dispensas = parsed.get("dispensas")
            if isinstance(dispensas, list) and not dispensas:
                return True
        return False

    def _try_with_images(self, blob_bytes: bytes, prompt: str) -> Optional[Dict[str, str]]:
        vision_model = os.getenv("VISION_MODEL")
        if not vision_model:
            _LOGGER.warning(
                "VISION_MODEL no está configurado; se omite fallback a modelo de imágenes"
            )
            return None

        images = self._convert_pdf_to_images(blob_bytes)
        if not images:
            return None

        client = self._client_factory.create_client()

        content_blocks = [{"type": "input_text", "text": prompt}]
        for index, image_bytes in enumerate(images, start=1):
            data_url = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('ascii')}"
            content_blocks.append({"type": "input_image", "image_url": data_url})
            _LOGGER.debug("Se añadió imagen %s al payload de fallback", index)

        response = client.responses.create(
            model=vision_model,
            input=[{"role": "user", "content": content_blocks}],
        )

        content = getattr(response, "output_text", "") or ""
        if not content and getattr(response, "output", None):
            block = response.output[0]
            if getattr(block, "content", None):
                part = block.content[0]
                if hasattr(part, "text") and hasattr(part.text, "value"):
                    content = part.text.value

        return {"response_id": response.id, "content": content}

    def _convert_pdf_to_images(self, blob_bytes: bytes) -> List[bytes]:
        try:
            import fitz  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependencia opcional
            _LOGGER.warning(
                "PyMuPDF (pymupdf) no está instalado; no se puede hacer fallback a imágenes"
            )
            return []

        doc = fitz.open(stream=blob_bytes, filetype="pdf")
        images: List[bytes] = []
        for page_index, page in enumerate(doc, start=1):
            pix = page.get_pixmap()
            images.append(pix.tobytes("png"))
            _LOGGER.debug("Página %s convertida a PNG para fallback", page_index)
        return images

    def _persist_processed_result(
        self,
        container_name: str,
        blob_name: str,
        result: Dict[str, str],
    ) -> None:
        response_id = result.get("response_id")
        if not response_id:
            _LOGGER.debug("Resultado sin response_id; se omite persistencia")
            return

        segments = [segment for segment in blob_name.strip("/").split("/") if segment]
        if len(segments) < 3:
            _LOGGER.debug(
                "El blob '%s' no contiene suficientes segmentos para determinar el proyecto",
                blob_name,
            )
            return

        base_path, project = segments[0], segments[1]
        document_name = segments[-1]
        stem = Path(document_name).stem or document_name
        target_blob = f"{base_path}/{project}/processed/{stem}.json"

        payload = {
            "response_id": response_id,
            "content": result.get("content", ""),
        }

        self._blob_repository.upload_content_to_blob(
            payload,
            blob_name=target_blob,
            container_name=container_name,
            indent_json=True,
        )
        _LOGGER.info(
            "Resultado almacenado en '%s' para el proyecto '%s'",
            target_blob,
            project,
        )
