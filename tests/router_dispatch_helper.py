#!/usr/bin/env python3
"""Simula mensajes hacia dispensa-router-in para proyectos o documentos."""
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from azure.storage.blob import BlobServiceClient


ROOT = Path(__file__).resolve().parents[1]


def _debug(message: str, **extra: Any) -> None:
    # Depuración deshabilitada; mantener por compatibilidad con llamadas existentes.
    return


def _load_local_settings() -> Dict[str, str]:
    settings_path = ROOT / "local.settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    values = data.get("Values", {})
    _debug(f"local.settings.json detectado con {len(values)} claves", keys=list(values.keys()))
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


def _log_json(level: str, message: str, **extra: Any) -> None:
    payload: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level.upper(),
        "logger": "router_dispatch_helper",
        "message": message,
    }
    if extra:
        for key, value in extra.items():
            if value is not None:
                payload[key] = value
    print(json.dumps(payload, ensure_ascii=False))


def _load_documents_from_project(project_id: str) -> List[str]:
    connection = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.environ["DEFAULT_BLOB_CONTAINER"]
    client = BlobServiceClient.from_connection_string(connection)
    container_client = client.get_container_client(container)
    prefix = f"basedocuments/{project_id.strip('/')}/raw/"
    names = [blob.name for blob in container_client.list_blobs(name_starts_with=prefix)]
    _debug("Documentos listados para proyecto", project_id=project_id, total=len(names))
    return names


def list_all_projects() -> List[str]:
    """Obtiene todos los project_id que tienen blobs bajo <DOCUMENTS_BASE_PATH>/<project_id>/raw/"""
    connection = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    container = os.environ["DEFAULT_BLOB_CONTAINER"]
    base_path = os.getenv("DOCUMENTS_BASE_PATH", "basedocuments").strip("/")
    raw_folder = os.getenv("RAW_DOCUMENTS_FOLDER", "raw").strip("/")

    client = BlobServiceClient.from_connection_string(connection)
    container_client = client.get_container_client(container)

    prefix = f"{base_path}/"
    project_ids = set()
    for blob in container_client.list_blobs(name_starts_with=prefix):
        # Esperado: basedocuments/<project_id>/raw/...
        parts = blob.name.split("/")
        if len(parts) >= 3 and parts[0] == base_path and parts[2] == raw_folder:
            project_ids.add(parts[1])
    projects = sorted(project_ids)
    _debug("Proyectos detectados en storage", total=len(projects), projects=projects)
    return projects


def dispatch_project(project_id: str, seq: Optional[int] = None, total: Optional[int] = None) -> None:
    documents = _load_documents_from_project(project_id)
    _log_json(
        "INFO",
        f"Enviando proyecto '{project_id}' con {len(documents)} documentos",
        project_id=project_id,
        sequence=seq,
        total=total,
        document_count=len(documents),
    )

    if not documents:
        print(f"⚠️ Proyecto {project_id} sin documentos en raw/")
        return

    per_document_delay = int(os.getenv("DOCUMENT_DELAY_SECONDS", "5"))
    for index, document in enumerate(documents, start=1):
        _debug(
            "Despachando documento individual",
            project_id=project_id,
            document=document,
            document_index=index,
            document_total=len(documents),
        )
        dispatch_document(project_id, document)
        if index < len(documents) and per_document_delay > 0:
            time.sleep(per_document_delay)

    if seq is not None and total is not None:
        print(f"✅ Enviado [{seq}/{total}] proyecto={project_id} ({len(documents)} documentos)")
    else:
        print(f"✅ Enviado proyecto={project_id} ({len(documents)} documentos)")


def dispatch_document(project_id: str, document_name: str) -> None:
    payload = {
        "project_id": project_id,
        "trigger_type": "document",
        "documents": [document_name],
    }
    _debug("Payload document", payload=payload)
    message = FakeServiceBusMessage(payload)
    function_app.router(message)


def _split_delay_args(args: List[str]) -> Tuple[List[str], Optional[int], List[str]]:
    clean_args: List[str] = []
    delay: Optional[int] = None
    excluded: List[str] = []
    for arg in args:
        if arg.startswith("--delay="):
            try:
                delay = int(arg.split("=", 1)[1])
            except ValueError:
                print(f"[WARN] Valor de delay no válido: {arg}")
        elif arg.startswith("--except=") or arg.startswith("--exclude="):
            _, value = arg.split("=", 1)
            candidate = value.strip()
            if candidate:
                excluded.append(candidate)
        elif arg.startswith("--except") or arg.startswith("--exclude"):
            print(f"[WARN] Se esperaba formato --except=PROYECTO, argumento ignorado: {arg}")
        else:
            clean_args.append(arg)
    _debug("Argumentos procesados", clean_args=clean_args, delay=delay, excluded=excluded)
    return clean_args, delay, excluded


def main(argv: List[str]) -> None:
    if len(argv) < 2:
        print(
            "Uso: python3 tests/router_dispatch_helper.py <project_id> [documento] | ALL [--delay=seg]"
        )
        raise SystemExit(1)

    raw_args, delay_override, excluded = _split_delay_args(argv[1:])
    if not raw_args:
        print(
            "Uso: python3 tests/router_dispatch_helper.py <project_id> [documento] | ALL [--delay=seg]"
        )
        raise SystemExit(1)

    target = raw_args[0]
    _debug("Target principal", target=target, args=raw_args, delay_override=delay_override)

    # Soporta ejecutar todos los proyectos con un delay configurable (por defecto 300s)
    if target.upper() in ("ALL", "*"):
        delay = delay_override or int(os.getenv("DISPATCH_DELAY_SECONDS", "300"))
        projects = [p for p in list_all_projects() if p not in excluded]
        if not projects:
            if excluded:
                print("[INFO] No hay proyectos para procesar después de aplicar las exclusiones.")
            else:
                print("[INFO] No se encontraron proyectos en Blob Storage bajo DOCUMENTS_BASE_PATH/raw")
            return
        if excluded:
            _log_json("INFO", "Proyectos excluidos", excluded=excluded)
        _log_json("INFO", f"Proyectos encontrados: {projects}", count=len(projects))
        print(f"🔎 Proyectos a enviar: {len(projects)} -> {projects}")

        total = len(projects)
        sent = 0
        queue_name = getattr(function_app, "ROUTER_QUEUE_NAME", "dispensas-router-in")

        print(f"⏱️ Intervalo entre envíos: {delay} segundos")
        for idx, project_id in enumerate(projects, start=1):
            print(f"🚀 Procesando [{idx}/{total}] proyecto={project_id}")
            _debug("Disparando proyecto (modo ALL)", index=idx, total=total, project_id=project_id, delay=delay)
            dispatch_project(project_id, idx, total)
            sent += 1
            if idx < total:
                print(f"⏳ Esperando {delay} segundos antes del siguiente proyecto...")
                time.sleep(delay)
        print("📦 Cola:", queue_name)
        print(f"📊 Mensajes enviados: {sent}/{total}")
        print("✅ Envío de proyectos completado")
        return

    # Caso por proyecto o documento específico
    remaining = raw_args[1:]

    # Opción documento (formato original: script.py <project> <documento>)
    if len(remaining) == 1 and (("." in remaining[0]) or ("/" in remaining[0])):
        dispatch_document(target, remaining[0])
        return

    # Múltiples proyectos proporcionados manualmente
    if remaining:
        projects = [p for p in [target, *remaining] if p not in excluded]
        delay = delay_override or int(os.getenv("DISPATCH_DELAY_SECONDS", "300"))
        if not projects:
            if excluded:
                print("[INFO] Todos los proyectos proporcionados quedaron excluidos.")
            else:
                print("[INFO] No se proporcionaron proyectos válidos para procesar.")
            return
        _log_json("INFO", f"Proyectos recibidos manualmente: {projects}", count=len(projects))
        print(f"🔎 Proyectos a enviar: {len(projects)} -> {projects}")
        print(f"⏱️ Intervalo entre envíos: {delay} segundos")
        queue_name = getattr(function_app, "ROUTER_QUEUE_NAME", "dispensas-router-in")
        for idx, project_id in enumerate(projects, start=1):
            print(f"🚀 Procesando [{idx}/{len(projects)}] proyecto={project_id}")
            _debug("Disparando proyecto (lista manual)", index=idx, total=len(projects), project_id=project_id, delay=delay)
            dispatch_project(project_id, idx, len(projects))
            if idx < len(projects):
                print(f"⏳ Esperando {delay} segundos antes del siguiente proyecto...")
                time.sleep(delay)
        print("📦 Cola:", queue_name)
        print(f"📊 Mensajes enviados: {len(projects)}/{len(projects)}")
        print("✅ Envío de proyectos completado")
        return

    # Proyecto único
    project = target
    if project in excluded:
        print(f"[INFO] Proyecto '{project}' está en la lista de exclusión. No se enviará.")
        return
    if not remaining:
        _debug("Modo proyecto único sin documentos adicionales", project=project)
        dispatch_project(project)
    else:
        _debug("Modo documento específico", project=project, document=remaining[0])
        dispatch_document(project, remaining[0])


if __name__ == "__main__":
    main(sys.argv)
