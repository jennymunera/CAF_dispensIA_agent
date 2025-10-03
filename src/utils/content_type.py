from typing import Tuple

_CONTENT_TYPE_MAP = {
    # Texto
    "txt": "text/plain",
    "md": "text/markdown",
    "csv": "text/csv",
    "json": "application/json",
    "xml": "application/xml",
    "html": "text/html",
    "htm": "text/html",
    # Documentos
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def guess_filename_and_content_type(blob_name: str) -> Tuple[str, str]:
    if not blob_name:
        raise ValueError("El nombre del blob no puede estar vacío")

    if "." in blob_name:
        extension = blob_name.split(".")[-1].lower()
    else:
        extension = "txt"

    content_type = _CONTENT_TYPE_MAP.get(extension, "application/octet-stream")

    if not blob_name.endswith(f".{extension}"):
        filename = f"{blob_name}.{extension}"
    else:
        filename = blob_name

    return filename, content_type
