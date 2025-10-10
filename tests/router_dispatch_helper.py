#!/usr/bin/env python3
"""Simula mensajes hacia dispensa-router-in para proyectos o documentos."""
import json
import os
import sys
import time
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


def list_all_projects() -> List[str]:
    """Obtiene todos los project_id que tienen blobs bajo <DOCUMENTS_BASE_PATH>/<project_id>/raw/"""
    connection = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.environ["DEFAULT_BLOB_CONTAINER"]
    base_path = os.getenv("DOCUMENTS_BASE_PATH", "basedocuments").strip("/")
    raw_folder = os.getenv("RAW_DOCUMENTS_FOLDER", "raw").strip("/")

    from azure.storage.blob import BlobServiceClient

    client = BlobServiceClient.from_connection_string(connection)
    container_client = client.get_container_client(container)

    prefix = f"{base_path}/"
    project_ids = set()
    for blob in container_client.list_blobs(name_starts_with=prefix):
        # Esperado: basedocuments/<project_id>/raw/...
        parts = blob.name.split("/")
        if len(parts) >= 3 and parts[0] == base_path and parts[2] == raw_folder:
            project_ids.add(parts[1])
    return sorted(project_ids)


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
        print(
            "Uso: python3 tests/router_dispatch_helper.py <project_id> [documento] | ALL [--delay=seg]"
        )
        raise SystemExit(1)

    target = argv[1]

    # Soporta ejecutar todos los proyectos con un delay configurable (por defecto 180s)
    if target.upper() in ("ALL", "*"):
        delay = int(os.getenv("DISPATCH_DELAY_SECONDS", "180"))
        # Permite override vía flag --delay=segundos
        for arg in argv[2:]:
            if arg.startswith("--delay="):
                try:
                    delay = int(arg.split("=", 1)[1])
                except ValueError:
                    print(f"[WARN] Valor de delay no válido: {arg}")
        projects = list_all_projects()
        if not projects:
            print("[INFO] No se encontraron proyectos en Blob Storage bajo DOCUMENTS_BASE_PATH/raw")
            return
        print(f"[INFO] Se encontraron {len(projects)} proyectos. Delay entre envíos: {delay}s")
        for idx, project_id in enumerate(projects, start=1):
            print(f"[RUN {idx}/{len(projects)}] Proyecto: {project_id}")
            dispatch_project(project_id)
            if idx < len(projects):
                print(f"[SLEEP] Esperando {delay} segundos antes del siguiente proyecto...")
                time.sleep(delay)
        print("[DONE] Envío de proyectos completado")
        return

    # Caso por proyecto o documento específico
    project = target
    if len(argv) == 2:
        dispatch_project(project)
    else:
        dispatch_document(project, argv[2])


if __name__ == "__main__":
    main(sys.argv)
