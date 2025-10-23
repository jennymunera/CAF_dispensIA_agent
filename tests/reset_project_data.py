#!/usr/bin/env python3
"""
Resetea datos de un proyecto eliminando blobs en:
- basedocuments/<project>/processed/
- basedocuments/<project>/results/dispensas/
- basedocuments/<project>/results/dispensas_results.json
- basedocuments/<project>/results/csv_generation.done y .csv_generation.lock

Nota: no elimina output CSV bajo results/outputdocuments/.

Usa:
- AZURE_STORAGE_CONNECTION_STRING
- DEFAULT_BLOB_CONTAINER

Uso:
  python3 tests/reset_project_data.py <PROJECT_ID> [--dry-run] [--force]

Ejemplos:
  # Ver qué se borraría (sin borrar)
  python3 tests/reset_project_data.py CFA007671 --dry-run

  # Borrar confirmando automáticamente
  python3 tests/reset_project_data.py CFA007671 --force
"""
import os
import sys
import argparse
from typing import List
from azure.storage.blob import BlobServiceClient
import json


def _list_blobs(client: BlobServiceClient, container: str, prefix: str) -> List[str]:
    container_client = client.get_container_client(container)
    return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]


def _delete_blob(client: BlobServiceClient, container: str, name: str) -> None:
    blob_client = client.get_blob_client(container=container, blob=name)
    blob_client.delete_blob()


def _delete_by_prefix(client: BlobServiceClient, container: str, prefix: str, dry_run: bool) -> int:
    names = _list_blobs(client, container, prefix)
    for name in names:
        if dry_run:
            print(f"[DRY-RUN] - {name}")
        else:
            _delete_blob(client, container, name)
            print(f"[DELETE]  - {name}")
    return len(names)


def load_local_settings(settings_path: str = None) -> dict:
    paths_to_try = []
    if settings_path:
        paths_to_try.append(settings_path)
    paths_to_try.append(os.path.join(os.getcwd(), "local.settings.json"))
    paths_to_try.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "local.settings.json")))
    for p in paths_to_try:
        try:
            with open(p, "r") as f:
                data = json.load(f)
            vals = data.get("Values") or {}
            if vals:
                print(f"Usando valores desde {p}")
                return vals
        except Exception:
            pass
    return {}


def main(argv: List[str]) -> None:
    parser = argparse.ArgumentParser(description="Reset de datos de un proyecto en Blob Storage")
    parser.add_argument("project_id", help="ID del proyecto a resetear")
    parser.add_argument("--dry-run", action="store_true", help="No borrar, solo listar lo que se borraría")
    parser.add_argument("--force", action="store_true", help="No pedir confirmación, borrar directamente")
    args = parser.parse_args(argv)

    settings = load_local_settings()
    conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING") or settings.get("AZURE_STORAGE_CONNECTION_STRING")
    container = os.getenv("DEFAULT_BLOB_CONTAINER") or settings.get("DEFAULT_BLOB_CONTAINER")
    base_path = os.getenv("DOCUMENTS_BASE_PATH") or settings.get("DOCUMENTS_BASE_PATH") or "basedocuments"

    if not conn or not container:
        print("ERROR: Debes configurar AZURE_STORAGE_CONNECTION_STRING y DEFAULT_BLOB_CONTAINER (en entorno o en local.settings.json)")
        sys.exit(1)

    client = BlobServiceClient.from_connection_string(conn)
    project = (args.project_id or "").strip("/")

    prefixes = [
        f"{base_path}/{project}/processed/",
        f"{base_path}/{project}/results/dispensas/",
    ]

    single_blobs = [
        f"{base_path}/{project}/results/dispensas_results.json",
        f"{base_path}/{project}/results/csv_generation.done",
        f"{base_path}/{project}/results/.csv_generation.lock",
    ]

    print(f"Container: {container}")
    print(f"Proyecto:  {project}")
    print(f"BasePath:  {base_path}")
    print("--------------------------------------------")

    if not args.force and not args.dry_run:
        try:
            confirm = input(
                "Esto borrará processed/, results/dispensas/, resultados agregados y marcadores. ¿Continuar? [y/N]: "
            ).strip().lower()
        except KeyboardInterrupt:
            print("\nCancelado")
            sys.exit(1)
        if confirm not in ("y", "yes", "s", "si"):
            print("Operación cancelada.")
            sys.exit(0)

    total = 0
    for prefix in prefixes:
        print(f"Borrando por prefijo: {prefix}")
        total += _delete_by_prefix(client, container, prefix, args.dry_run)

    print("Borrando blobs individuales:")
    for name in single_blobs:
        # Si existe, borrar; si no, ignorar
        names = _list_blobs(client, container, name)
        if not names:
            print(f"[SKIP]    - {name} (no existe)")
            continue
        if args.dry_run:
            print(f"[DRY-RUN] - {name}")
        else:
            _delete_blob(client, container, name)
            print(f"[DELETE]  - {name}")
        total += 1

    print("--------------------------------------------")
    print(f"Elementos afectados: {total} {'(simulado)' if args.dry_run else ''}")
    print("Reset completado.")


if __name__ == "__main__":
    main(sys.argv[1:])