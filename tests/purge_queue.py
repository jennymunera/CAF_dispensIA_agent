# Script para purgar una cola de Azure Service Bus
"""Uso:
    python3 tests/purge_queue.py [cola_1] [cola_2] ...

Sin argumentos purga las colas principales del proyecto.
La cadena de conexión se toma de TEST_SERVICE_BUS_CONNECTION o SERVICE_BUS_CONNECTION,
con fallback a los valores de local.settings.json.
"""
import json
import os
import sys
from pathlib import Path

from typing import Dict

from azure.servicebus import ServiceBusClient


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


DEFAULT_QUEUES = ["dispensas-router-in", "dispensas-process-in"]


def _purge_queue(client: ServiceBusClient, queue_name: str) -> None:
    receiver = client.get_queue_receiver(queue_name, max_wait_time=5)
    with receiver:
        total = 0
        while True:
            msgs = receiver.receive_messages(max_message_count=50)
            if not msgs:
                break
            for msg in msgs:
                receiver.complete_message(msg)
            total += len(msgs)
            print(f"[{queue_name}] Eliminados {len(msgs)} mensajes del batch")
    print(f"[{queue_name}] Total eliminados: {total}")


def main() -> None:
    connection = os.environ.get("TEST_SERVICE_BUS_CONNECTION") or os.environ.get("SERVICE_BUS_CONNECTION")
    if not connection:
        raise RuntimeError(
            "Define TEST_SERVICE_BUS_CONNECTION o SERVICE_BUS_CONNECTION antes de ejecutar el script"
        )

    queue_names = sys.argv[1:] or DEFAULT_QUEUES

    with ServiceBusClient.from_connection_string(connection) as client:
        for queue_name in queue_names:
            _purge_queue(client, queue_name)


if __name__ == "__main__":
    main()
