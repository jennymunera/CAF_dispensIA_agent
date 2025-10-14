#!/usr/bin/env python3

"""Prueba manual del servicio OpenAIFileService usando un documento real."""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict

from azure.storage.blob import BlobServiceClient


ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "src" / "prompts" / "agente_unificado.txt"


def _load_local_settings() -> Dict[str, str]:
    settings_path = ROOT / "local.settings.json"
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"local.settings.json inválido: {exc}") from exc

    values = data.get("Values", {})
    return {key: str(value) for key, value in values.items()}


for key, value in _load_local_settings().items():
    os.environ.setdefault(key, value)

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import function_app

DOCUMENT_PATH = "basedocuments/CFA007671/raw/EED-048.PDF"


def _load_prompt() -> str:
    try:
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "No se encontró el archivo de prompt en src/prompts/agente_unificado.txt"
        ) from exc
    if not prompt:
        raise RuntimeError("El prompt unificado está vacío")
    return prompt


def _ensure_environment() -> None:
    for key, value in _load_local_settings().items():
        os.environ.setdefault(key, value)

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _build_blob_url(connection_string: str, container: str, blob_name: str) -> str:
    client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = client.get_blob_client(container=container, blob=blob_name)
    return blob_client.url


def _build_processed_blob_path(document_path: str) -> str:
    parts = [segment for segment in document_path.strip("/").split("/") if segment]
    if len(parts) < 3:
        raise ValueError("La ruta del documento no contiene los segmentos esperados")
    base_path, project = parts[0], parts[1]
    document_name = parts[-1]
    stem = Path(document_name).stem or document_name
    return f"{base_path}/{project}/processed/{stem}.json"


def _download_blob_text(connection_string: str, container: str, blob_name: str) -> str:
    client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = client.get_blob_client(container=container, blob=blob_name)
    return blob_client.download_blob().readall().decode("utf-8")


def _call_direct(blob_url: str, prompt: str, model: str, storage_conn: str, container: str) -> None:
    fallback_flag = {"used": False}
    original_try = function_app.openai_file_service._try_with_images

    def wrapped_try(blob_bytes, prompt_text):
        fallback_flag["used"] = True
        return original_try(blob_bytes, prompt_text)

    function_app.openai_file_service._try_with_images = wrapped_try

    try:
        print("[INFO] Ejecutando send_request_with_file directamente (sin HTTP)")
        result = function_app.openai_file_service.send_request_with_file(
            blob_url=blob_url,
            prompt=prompt,
            model=model,
        )
    finally:
        function_app.openai_file_service._try_with_images = original_try

    print(f"[DEBUG] Fallback a visión utilizado: {fallback_flag['used']}")
    _print_result(result, storage_conn, container)


def _print_result(data: Dict[str, str], storage_conn: str, container: str) -> None:
    response_id = data.get("response_id")
    content = data.get("content") or ""

    print(f"[RESULT] response_id: {response_id}")
    print("[RESULT] content:\n")
    print(content)

    if response_id:
        processed_blob = _build_processed_blob_path(DOCUMENT_PATH)
        try:
            stored = _download_blob_text(storage_conn, container, processed_blob)
        except Exception as exc:  # pragma: no cover - validación opcional
            print(f"[WARN] No se pudo leer el blob procesado '{processed_blob}': {exc}")
        else:
            print(f"[INFO] Blob almacenado: {processed_blob}")
            print(stored)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prueba de procesamiento de archivo con OpenAIFileService")
    parser.parse_args()

    print("=== Prueba directa de OpenAIFileService ===")
    _ensure_environment()

    try:
        storage_conn = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
        container = os.environ["DEFAULT_BLOB_CONTAINER"]
        model = os.environ.get("DEFAULT_OPENAI_MODEL", "gpt-5-mini")
    except KeyError as exc:
        print(f"[ERROR] Variable de entorno faltante: {exc}")
        raise SystemExit(1) from exc

    blob_url = _build_blob_url(storage_conn, container, DOCUMENT_PATH)
    prompt = _load_prompt()

    _call_direct(blob_url, prompt, model, storage_conn, container)

    print("=== Fin de la prueba ===")


if __name__ == "__main__":
    main()
