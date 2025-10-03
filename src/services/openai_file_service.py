import logging
import os
import tempfile
from typing import Dict

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
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(blob_bytes)
                temp_file_path = temp_file.name

            with open(temp_file_path, "rb") as file_handle:
                uploaded_file = client.files.create(file=file_handle, purpose="assistants")
                uploaded_file_id = uploaded_file.id

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
            return {"response_id": response.id, "content": content}
        except Exception:
            _LOGGER.exception("Error al procesar la solicitud con archivo para el blob '%s'", blob_name)
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
