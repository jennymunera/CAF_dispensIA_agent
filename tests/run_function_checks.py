#!/usr/bin/env python3
"""Pruebas manuales para las cuatro Azure Functions sin dependencia de frameworks."""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Callable, List, Tuple
import warnings

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_LOCAL_SETTINGS_PATH = _ROOT / "local.settings.json"


def _load_local_settings() -> dict:
    try:
        data = json.loads(_LOCAL_SETTINGS_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"local.settings.json inválido: {exc}")
    values = data.get("Values", {})
    return {key: str(value) for key, value in values.items()}


for key, value in _load_local_settings().items():
    os.environ.setdefault(key, value)

os.environ.setdefault("PYTHONWARNINGS", "ignore")

logging.basicConfig(level=logging.CRITICAL)

try:
    from urllib3.exceptions import NotOpenSSLWarning  # type: ignore
except Exception:  # pragma: no cover - urllib3 puede no estar instalado
    NotOpenSSLWarning = None
else:
    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
warnings.simplefilter("ignore")
warnings.warn = lambda *_, **__: None  # type: ignore

import azure.functions as func  # type: ignore

import function_app


class FakeOpenAIChainedService:
    def __init__(self) -> None:
        self.last_call = None

    def send_chained_request(self, model: str, prompt: str, previous_response_id: str) -> dict:
        self.last_call = {
            "model": model,
            "prompt": prompt,
            "previous_response_id": previous_response_id,
        }
        return {
            "response_id": "chain-response-456",
            "content": "Respuesta encadenada",
        }


class FakeBlobDispatcherService:
    def __init__(self) -> None:
        self.last_message = None
        self.stub_tasks = [
            {"task_id": "task-1"},
            {"task_id": "task-2"},
        ]

    def generate_tasks(self, message) -> list:
        self.last_message = message
        return list(self.stub_tasks)


class FakeServiceBusDispatcher:
    def __init__(self) -> None:
        self.last_tasks = None

    def send_tasks(self, tasks) -> int:
        self.last_tasks = list(tasks)
        return len(tasks)


class FakeDispensasProcessorService:
    def __init__(self) -> None:
        self.last_task = None

    def process(self, task) -> dict:
        self.last_task = task
        return {
            "project_id": task.project_id,
            "document_name": task.document_name,
            "initial_response": {"content": "texto"},
            "chained_response": None,
            "parsed_json": {"status": "ok"},
        }


# Inyección de dobles en function_app para aislar dependencias externas.
fake_chained_service = FakeOpenAIChainedService()
fake_blob_dispatcher = FakeBlobDispatcherService()
fake_service_bus_dispatcher = FakeServiceBusDispatcher()
fake_dispensas_processor = FakeDispensasProcessorService()

function_app.openai_chained_service = fake_chained_service
function_app.blob_dispatcher_service = fake_blob_dispatcher
function_app.service_bus_dispatcher = fake_service_bus_dispatcher
function_app.dispensas_processor_service = fake_dispensas_processor


def _decode_json_response(response: func.HttpResponse) -> dict:
    return json.loads(response.get_body().decode("utf-8"))


def test_chained_request_requires_previous_response_id() -> None:
    payload = {
        "prompt": "Continúa",
        "model": "gpt-5-mini",
        # Falta previous_response_id
    }
    request = func.HttpRequest(
        method="POST",
        url="http://localhost/chained-request",
        headers={"content-type": "application/json"},
        params={},
        body=json.dumps(payload).encode("utf-8"),
    )

    response = function_app.chained_request_http(request)

    assert response.status_code == 400, "Debe exigir previous_response_id"
    body = _decode_json_response(response)
    assert "previous_response_id" in body["error"], "El mensaje de error debe mencionar el campo faltante"


def test_chained_request_calls_service_with_payload() -> None:
    payload = {
        "prompt": "Continúa",
        "model": "gpt-5-mini",
        "previous_response_id": "resp-001",
    }
    request = func.HttpRequest(
        method="POST",
        url="http://localhost/chained-request",
        headers={"content-type": "application/json"},
        params={},
        body=json.dumps(payload).encode("utf-8"),
    )

    response = function_app.chained_request_http(request)

    assert response.status_code == 200, "Debe responder 200 cuando la solicitud es válida"
    body = _decode_json_response(response)
    assert body["response_id"] == "chain-response-456", "Debe propagar la respuesta del servicio"
    assert fake_chained_service.last_call == payload, "Debe reenviar el payload completo al servicio"


class FakeServiceBusMessage:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def get_body(self):  # pragma: no cover - método mínimo requerido por router
        return self._body


def test_router_raises_with_invalid_json() -> None:
    class BrokenMessage:
        def get_body(self):
            return b"{invalid"

    message = BrokenMessage()

    try:
        function_app.router(message)
    except ValueError:
        return
    raise AssertionError("Debe elevar ValueError cuando el JSON es inválido")


def test_router_dispatches_generated_tasks() -> None:
    payload = {
        "project_id": "demo-project",
        "trigger_type": "project",
        "model": "gpt-4",
        "agent_prompt": "Agente",
        "chained_prompt": "Chained",
    }
    message = FakeServiceBusMessage(payload)

    function_app.router(message)

    assert fake_blob_dispatcher.last_message.project_id == "demo-project", "Debe traducir el mensaje de la cola"
    assert fake_service_bus_dispatcher.last_tasks == fake_blob_dispatcher.stub_tasks, "Debe reenviar todas las tareas generadas"


class FakeDispensasMessage:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def get_body(self):
        return self._body


def test_dispensas_process_requires_valid_task_payload() -> None:
    message = FakeDispensasMessage({"invalid": True})

    try:
        function_app.dispensas_process(message)
    except ValueError:
        return
    raise AssertionError("Debe elevar ValueError con tareas mal construidas")


def test_dispensas_process_invokes_processor_service() -> None:
    payload = {
        "project_id": "demo-project",
        "blob_url": "https://storage/raw/doc.pdf",
        "model": "gpt-4",
        "agent_prompt": "Agente",
        "chained_prompt": "Chained",
        "document_name": "doc.pdf",
    }
    message = FakeDispensasMessage(payload)

    function_app.dispensas_process(message)

    task = fake_dispensas_processor.last_task
    assert task is not None, "Debe enviar la tarea al servicio de procesamiento"
    assert task.project_id == "demo-project", "El task debe conservar project_id"
    assert task.blob_url.endswith("doc.pdf"), "El task debe conservar el blob"


_TESTS: List[Tuple[str, Callable[[], None]]] = [
    ("chained_request exige previous_response_id", test_chained_request_requires_previous_response_id),
    ("chained_request reenvía el payload al servicio", test_chained_request_calls_service_with_payload),
    ("router falla con JSON inválido", test_router_raises_with_invalid_json),
    ("router envía tareas generadas", test_router_dispatches_generated_tasks),
    ("dispensas_process valida el payload", test_dispensas_process_requires_valid_task_payload),
    ("dispensas_process llama al procesador", test_dispensas_process_invokes_processor_service),
]


def _run_test(name: str, callable_: Callable[[], None]) -> bool:
    try:
        callable_()
    except AssertionError as exc:
        print(f"[FAIL] {name}: {exc}")
        return False
    except Exception as exc:  # pragma: no cover - reportar errores inesperados
        print(f"[ERROR] {name}: {exc}")
        return False
    else:
        print(f"[OK] {name}")
        return True


def main() -> None:
    passed = sum(1 for name, fn in _TESTS if _run_test(name, fn))
    total = len(_TESTS)
    print(f"\n{passed}/{total} pruebas completadas con éxito")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
