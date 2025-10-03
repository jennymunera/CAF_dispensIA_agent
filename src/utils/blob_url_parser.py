from typing import Tuple
from urllib.parse import urlparse, unquote


def parse_blob_url(blob_url: str) -> Tuple[str, str]:
    if not blob_url:
        raise ValueError("La URL del blob no puede estar vacía")

    parsed = urlparse(blob_url)

    if not parsed.path:
        raise ValueError("La URL del blob no tiene una ruta válida")

    path = parsed.path.lstrip("/")
    if not path:
        raise ValueError("La URL del blob no contiene información de contenedor y blob")

    segments = path.split("/")
    container_name = segments[0]
    if not container_name:
        raise ValueError("La URL del blob no especifica el contenedor")

    blob_name = "/".join(segments[1:])
    if not blob_name:
        raise ValueError("La URL del blob no especifica el nombre del blob")

    return container_name, unquote(blob_name)
