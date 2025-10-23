#!/usr/bin/env python3
"""
Elimina marcadores de generación de CSV en Blob Storage por proyecto.

Ubicación por defecto:
  basedocuments/<project_id>/results/csv_generation.done
Opcionalmente también:
  basedocuments/<project_id>/results/.csv_generation.lock

Carga configuración desde local.settings.json si las variables de entorno no están presentes.

Uso:
  python3 tests/delete_csv_done.py --all
  python3 tests/delete_csv_done.py --project CFA008390 --include-lock
  python3 tests/delete_csv_done.py --all --dry-run
  python3 tests/delete_csv_done.py --all --base basedocuments --results results

Flags:
  --all             Borra marcadores para todos los proyectos detectados
  --project -p      Borra marcadores para uno o varios proyectos (repetible)
  --include-lock    Incluye la eliminación de .csv_generation.lock
  --dry-run         Muestra lo que se borraría sin eliminar
  --base            Override de DOCUMENTS_BASE_PATH (por defecto 'basedocuments')
  --results         Override de RESULTS_FOLDER (por defecto 'results')
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

from azure.storage.blob import BlobServiceClient

ROOT = Path(__file__).resolve().parents[1]


def _load_local_settings() -> Dict[str, str]:
    settings_path = ROOT / "local.settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    values = data.get("Values", {})
    return {key: str(value) for key, value in values.items()}


def _ensure_environment() -> None:
    for key, value in _load_local_settings().items():
        os.environ.setdefault(key, value)


def _list_all_projects(client: BlobServiceClient, container: str, base_path: str, raw_folder: str = "raw") -> List[str]:
    container_client = client.get_container_client(container)
    prefix = f"{base_path.strip('/')}/"
    projects = set()
    for blob in container_client.list_blobs(name_starts_with=prefix):
        # Esperado: basedocuments/<project_id>/raw/...
        parts = blob.name.split("/")
        if len(parts) >= 3 and parts[0] == base_path.strip("/") and parts[2] == raw_folder.strip("/"):
            projects.add(parts[1])
    return sorted(projects)


def _delete_blob(client: BlobServiceClient, container: str, blob_name: str, dry_run: bool = False) -> bool:
    blob_client = client.get_blob_client(container=container, blob=blob_name)
    try:
        exists = blob_client.exists()
    except Exception as exc:
        print(f"[ERROR] No se pudo verificar existencia de '{blob_name}': {exc}")
        return False

    if not exists:
        print(f"[SKIP] No existe: {blob_name}")
        return False

    if dry_run:
        print(f"[DRY] Se eliminaría: {blob_name}")
        return False

    try:
        blob_client.delete_blob()
        print(f"[OK] Eliminado: {blob_name}")
        return True
    except Exception as exc:
        print(f"[ERROR] No se pudo eliminar '{blob_name}': {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Borra csv_generation.done por proyecto en Blob Storage")
    parser.add_argument("--all", action="store_true", help="Borrar todos los proyectos detectados")
    parser.add_argument("--project", "-p", action="append", help="ID de proyecto (repetible)")
    parser.add_argument("--include-lock", action="store_true", help="También borrar .csv_generation.lock")
    parser.add_argument("--dry-run", action="store_true", help="Mostrar sin eliminar")
    parser.add_argument("--base", default=os.getenv("DOCUMENTS_BASE_PATH", "basedocuments"), help="Base path")
    parser.add_argument("--results", default=os.getenv("RESULTS_FOLDER", "results"), help="Carpeta de resultados")
    parser.add_argument("--list", action="store_true", help="Listar proyectos con csv_generation.done")
    args = parser.parse_args()

    _ensure_environment()

    try:
        connection = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
        container = os.environ["DEFAULT_BLOB_CONTAINER"]
    except KeyError as exc:
        print(f"[ERROR] Variable de entorno faltante: {exc}")
        print("Asegúrate de definir AZURE_STORAGE_CONNECTION_STRING y DEFAULT_BLOB_CONTAINER.")
        raise SystemExit(1) from exc

    client = BlobServiceClient.from_connection_string(connection)

    targets: List[str] = []
    base_path = args.base.strip("/")
    results_folder = args.results.strip("/")

    # Modo listado de proyectos con csv_generation.done
    if args.list:
        container_client = client.get_container_client(container)
        prefix = f"{base_path}/"
        done_suffix = f"/{results_folder}/csv_generation.done"
        projects = set()
        for blob in container_client.list_blobs(name_starts_with=prefix):
            name = blob.name
            if name.endswith(done_suffix):
                parts = name.split("/")
                if len(parts) >= 3:
                    projects.add(parts[1])
        projects_sorted = sorted(projects)
        print(f"[LIST] Proyectos con csv_generation.done: {len(projects_sorted)}")
        for pid in projects_sorted:
            print(f"- {pid}")
        return

    if not args.all and not args.project:
        print("[ERROR] Debes especificar --all o al menos un --project/-p")
        raise SystemExit(2)

    # Construcción de rutas objetivo
    if args.all:
        # Listar todos los marcadores existentes para evitar operaciones innecesarias
        container_client = client.get_container_client(container)
        prefix = f"{base_path}/"
        done_suffix = f"/{results_folder}/csv_generation.done"
        lock_suffix = f"/{results_folder}/.csv_generation.lock"
        for blob in container_client.list_blobs(name_starts_with=prefix):
            name = blob.name
            if name.endswith(done_suffix):
                targets.append(name)
            elif args.include_lock and name.endswith(lock_suffix):
                targets.append(name)
    else:
        # Proyectos específicos
        for project_id in args.project:
            project = (project_id or "").strip("/")
            done_blob = f"{base_path}/{project}/{results_folder}/csv_generation.done"
            targets.append(done_blob)
            if args.include_lock:
                lock_blob = f"{base_path}/{project}/{results_folder}/.csv_generation.lock"
                targets.append(lock_blob)

    if not targets:
        print("[INFO] No se encontraron blobs objetivo para eliminar")
        return

    print(f"[INFO] Objetivos a procesar: {len(targets)}")

    deleted = 0
    for name in targets:
        if _delete_blob(client, container, name, dry_run=args.dry_run):
            deleted += 1

    print(f"[SUMMARY] Eliminados: {deleted} / Objetivos: {len(targets)} (dry_run={args.dry_run})")


if __name__ == "__main__":
    main()