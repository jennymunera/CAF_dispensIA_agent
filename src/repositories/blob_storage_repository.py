import json
import logging
from typing import List, Union

from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContentSettings

from src.interfaces.blob_storage_interface import BlobStorageInterface


class BlobStorageRepository(BlobStorageInterface):
    def __init__(self, connection_string: str, default_container: str) -> None:
        self.blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        self.default_container = default_container

    def upload_content_to_blob(
        self,
        content: Union[str, dict, list],
        blob_name: str,
        container_name: str = "",
        indent_json: bool = True
    ) -> None:
        """Sube contenido de texto o JSON a Blob Storage."""
        try:
            container = container_name or self.default_container

            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False, indent=2 if indent_json else None)
            elif not isinstance(content, str):
                content = str(content)

            content_bytes = content.encode("utf-8")
            blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob_name)
            blob_client.upload_blob(content_bytes, overwrite=True)
        except AzureError as exc:
            logging.error(
                "Error subiendo contenido al blob '%s' en el contenedor '%s': %s",
                blob_name,
                container,
                exc,
            )
            raise
        except Exception as exc:
            logging.exception("Error inesperado en upload_content_to_blob: %s", exc)
            raise

    def upload_bytes_to_blob(
        self,
        content: bytes,
        blob_name: str,
        container_name: str = "",
        content_type: str = "application/octet-stream"
    ) -> None:
        try:
            container = container_name or self.default_container
            blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob_name)
            content_settings = ContentSettings(content_type=content_type)
            blob_client.upload_blob(content, overwrite=True, content_settings=content_settings)
        except AzureError as exc:
            logging.error(
                "Error subiendo bytes al blob '%s' en el contenedor '%s': %s",
                blob_name,
                container,
                exc,
            )
            raise
        except Exception as exc:
            logging.exception("Error inesperado en upload_bytes_to_blob: %s", exc)
            raise

    def read_item_from_blob(
        self,
        blob_name: str,
        container_name: str = ""
    ) -> bytes:
        """Descarga un blob de Azure Blob Storage y lo retorna como bytes."""
        try:
            container = container_name or self.default_container
            blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob_name)
            download_stream = blob_client.download_blob()
            return download_stream.readall()
        except ResourceNotFoundError as exc:
            logging.error(
                "El blob '%s' no fue encontrado en el contenedor '%s': %s",
                blob_name,
                container,
                exc,
            )
            raise
        except AzureError as exc:
            logging.error(
                "Error descargando el blob '%s' desde el contenedor '%s': %s",
                blob_name,
                container,
                exc,
            )
            raise
        except Exception as exc:
            logging.exception("Error inesperado en read_item_from_blob: %s", exc)
            raise

    def list_blobs(
        self,
        prefix: str = "",
        container_name: str = ""
    ) -> List[str]:
        """Lista blobs en el contenedor opcionalmente filtrando por prefijo."""
        try:
            container = container_name or self.default_container
            container_client = self.blob_service_client.get_container_client(container)
            return [blob.name for blob in container_client.list_blobs(name_starts_with=prefix)]
        except ResourceNotFoundError as exc:
            logging.error("El contenedor '%s' no fue encontrado: %s", container, exc)
            raise
        except AzureError as exc:
            logging.error("Error listando blobs en el contenedor '%s': %s", container, exc)
            raise
        except Exception as exc:
            logging.exception("Error inesperado en list_blobs: %s", exc)
            raise

    def delete_blob(
        self,
        blob_name: str,
        container_name: str = ""
    ) -> None:
        try:
            container = container_name or self.default_container
            blob_client = self.blob_service_client.get_blob_client(container=container, blob=blob_name)
            blob_client.delete_blob()
        except ResourceNotFoundError:
            logging.debug("Se intentó eliminar el blob inexistente '%s' en '%s'", blob_name, container)
        except AzureError as exc:
            logging.error(
                "Error eliminando el blob '%s' en el contenedor '%s': %s",
                blob_name,
                container,
                exc,
            )
            raise
        except Exception as exc:
            logging.exception("Error inesperado en delete_blob: %s", exc)
            raise
