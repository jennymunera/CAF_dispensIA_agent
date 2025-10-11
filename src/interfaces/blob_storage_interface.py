from abc import ABC, abstractmethod
from typing import List, Union


class BlobStorageInterface(ABC):
    @abstractmethod
    def upload_content_to_blob(
        self,
        content: Union[str, dict, list],
        blob_name: str,
        container_name: str = "",
        indent_json: bool = True
    ) -> None:
        pass

    @abstractmethod
    def upload_bytes_to_blob(
        self,
        content: bytes,
        blob_name: str,
        container_name: str = "",
        content_type: str = "application/octet-stream"
    ) -> None:
        """
        Sube contenido binario (bytes) a Blob Storage.
        """
        pass

    @abstractmethod
    def read_item_from_blob(
        self,
        blob_name: str,
        container_name: str = ""
    ) -> bytes:
        pass

    @abstractmethod
    def list_blobs(
        self,
        prefix: str = "",
        container_name: str = ""
    ) -> List[str]:
        pass

    @abstractmethod
    def delete_blob(
        self,
        blob_name: str,
        container_name: str = ""
    ) -> None:
        pass
