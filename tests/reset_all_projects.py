#!/usr/bin/env python3
"""
Resetea datos de TODOS los proyectos dentro de DOCUMENTS_BASE_PATH en el contenedor.

Qué borra por cada proyecto:
- basedocuments/<project>/processed/
- basedocuments/<project>/results/dispensas/
- basedocuments/<project>/results/dispensas_results.json
- basedocuments/<project>/results/csv_generation.done y .csv_generation.lock

Nota: no elimina output CSV bajo results/outputdocuments/.

Usa:
- AZURE_STORAGE_CONNECTION_STRING (obligatorio)
- DEFAULT_BLOB_CONTAINER (obligatorio)
- DOCUMENTS_BASE_PATH (opcional, por defecto 'basedocuments')

Uso:
  python3 tests/reset_all_projects.py [--dry-run] [--force] [--prefix PREFIJO] [--limit N]

Ejemplos:
  # Vista previa de todo sin borrar
  python3 tests/reset_all_projects.py --dry-run

  # Borrar todo con confirmación interactiva
  python3 tests/reset_all_projects.py

  # Borrar todo sin confirmar
  python3 tests/reset_all_projects.py --force

  # Limitar a proyectos cuyo id comienza por 'CFA'
  python3 tests/reset_all_projects.py --prefix CFA --force

  # Limitar a los primeros 10 proyectos encontrados
  python3 tests/reset_all_projects.py --limit 10 --force
"""

import os
import sys
import argparse
from typing import Iterable, Set, List
import json

try:
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ResourceNotFoundError
except Exception as e:
    print("Falta azure-storage-blob. Instala dependencias: pip install -r requirements.txt")
    raise


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


def get_env(name: str, default: str = None, required: bool = False, settings: dict = None) -> str:
    val = os.environ.get(name)
    if not val and settings:
        val = settings.get(name)
    if not val:
        val = default
    if required and not val:
        print(f"Variable de entorno requerida no definida: {name}")
        print("Provee la variable en el entorno o en local.settings.json bajo 'Values'.")
        sys.exit(1)
    return val


def list_projects(container_client, base_path: str, prefix_filter: str = "") -> List[str]:
    projects: Set[str] = set()
    start = f"{base_path}/"
    for blob in container_client.list_blobs(name_starts_with=start):
        # Esperado: basedocuments/<project>/...
        parts = blob.name.split("/")
        if len(parts) >= 2:
            project_id = parts[1]
            if prefix_filter and not project_id.startswith(prefix_filter):
                continue
            projects.add(project_id)
    return sorted(projects)


def delete_blob_if_exists(container_client, blob_name: str, dry_run: bool):
    if dry_run:
        print(f"[DRY-RUN] delete_blob {blob_name}")
        return
    try:
        container_client.delete_blob(blob_name)
        print(f"Deleted {blob_name}")
    except ResourceNotFoundError:
        # ya no existe, ignorar
        pass


def delete_paths_for_project(container_client, base_path: str, project: str, dry_run: bool):
    prefixes = [
        f"{base_path}/{project}/processed/",
        f"{base_path}/{project}/results/dispensas/",
    ]
    single_blobs = [
        f"{base_path}/{project}/results/dispensas_results.json",
        f"{base_path}/{project}/results/csv_generation.done",
        f"{base_path}/{project}/results/.csv_generation.lock",
    ]

    # Eliminar por prefijo (todos los blobs dentro)
    for p in prefixes:
        print(f"Scanning prefix: {p}")
        for blob in container_client.list_blobs(name_starts_with=p):
            delete_blob_if_exists(container_client, blob.name, dry_run)

    # Eliminar blobs individuales
    for b in single_blobs:
        delete_blob_if_exists(container_client, b, dry_run)



def main():
    parser = argparse.ArgumentParser(description="Reset de datos para TODOS los proyectos")
    parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se borraría sin borrar")
    parser.add_argument("--force", action="store_true", help="Borra sin pedir confirmación")
    parser.add_argument("--prefix", type=str, default="", help="Filtra proyectos por prefijo")
    parser.add_argument("--limit", type=int, default=0, help="Limita el número de proyectos a procesar")
    args = parser.parse_args()

    settings = load_local_settings()
    conn = get_env("AZURE_STORAGE_CONNECTION_STRING", required=True, settings=settings)
    container_name = get_env("DEFAULT_BLOB_CONTAINER", required=True, settings=settings)
    base_path = get_env("DOCUMENTS_BASE_PATH", default="basedocuments", settings=settings)

    service_client = BlobServiceClient.from_connection_string(conn)
    container_client = service_client.get_container_client(container_name)

    projects = list_projects(container_client, base_path, args.prefix)
    if args.limit and args.limit > 0:
        projects = projects[: args.limit]

    if not projects:
        print("No se encontraron proyectos para resetear.")
        return

    print(f"Proyectos encontrados ({len(projects)}): {', '.join(projects)}")

    if not args.force:
        confirm = input("¿Deseas borrar datos de todos los proyectos listados? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelado.")
            return

    for project in projects:
        print(f"\n=== Reset proyecto: {project} ===")
        delete_paths_for_project(container_client, base_path, project, args.dry_run)

    print("\nReset completado.")


if __name__ == "__main__":
    main()