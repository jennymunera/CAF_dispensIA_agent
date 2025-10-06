#!/usr/bin/env python3
"""Simula mensajes hacia dispensa-router-in para proyectos o documentos."""
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]


def _load_local_settings() -> Dict[str, str]:
    settings_path = ROOT / "local.settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    values = data.get("Values", {})
    return {key: str(value) for key, value in values.items()}


for key, value in _load_local_settings().items():
    os.environ.setdefault(key, value)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import function_app  # noqa: E402


class FakeServiceBusMessage:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def get_body(self) -> bytes:
        return self._body


def _load_documents_from_project(project_id: str) -> List[str]:
    connection = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.environ["DEFAULT_BLOB_CONTAINER"]

    from azure.storage.blob import BlobServiceClient

    client = BlobServiceClient.from_connection_string(connection)
    container_client = client.get_container_client(container)

    prefix = f"basedocuments/{project_id.strip('/')}/raw/"
    return [blob.name for blob in container_client.list_blobs(name_starts_with=prefix)]


def dispatch_project(project_id: str) -> None:
    payload = {
        "project_id": project_id,
        "trigger_type": "project",
    }
    message = FakeServiceBusMessage(payload)
    print(f"[INFO] Enviando mensaje para proyecto '{project_id}'")
    function_app.router(message)
    print("[OK] Mensaje procesado por router")


def dispatch_document(project_id: str, document_name: str) -> None:
    payload = {
        "project_id": project_id,
        "trigger_type": "document",
        "documents": [document_name],
    }
    message = FakeServiceBusMessage(payload)
    print(f"[INFO] Enviando mensaje para documento '{document_name}' del proyecto '{project_id}'")
    function_app.router(message)
    print("[OK] Mensaje procesado por router")


def main(argv: List[str]) -> None:
    if len(argv) < 2:
        print("Uso: python3 tests/router_dispatch_helper.py <project_id> [documento]")
        raise SystemExit(1)

    project = argv[1]

    if len(argv) == 2:
        dispatch_project(project)
    else:
        dispatch_document(project, argv[2])


if __name__ == "__main__":
    main(sys.argv)
