# Script para purgar una cola de Azure Service Bus
"""Uso:
    python3 tests/purge_queue.py [cola_1] [cola_2] ...
    python3 tests/purge_queue.py --deadletter [cola_1] [cola_2] ...
    python3 tests/purge_queue.py --force [cola_1] [cola_2] ...
    python3 tests/purge_queue.py --deadletter --force [cola_1] [cola_2] ...
    python3 tests/purge_queue.py --wait=20 [opciones] [colas]

Sin argumentos purga las colas principales del proyecto.
La cadena de conexión se toma de TEST_SERVICE_BUS_CONNECTION o SERVICE_BUS_CONNECTION,
con fallback a los valores de local.settings.json.
"""
import json
import os
import sys
from pathlib import Path

from typing import Dict

from azure.servicebus import ServiceBusClient, ServiceBusSubQueue, ServiceBusReceiveMode


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


def _purge_queue(
    client: ServiceBusClient,
    queue_name: str,
    deadletter: bool = False,
    force: bool = False,
    wait_time: int = 5,
) -> None:
    display_name = f"{queue_name} (DLQ)" if deadletter else queue_name
    receiver = client.get_queue_receiver(
        queue_name,
        max_wait_time=wait_time,
        sub_queue=ServiceBusSubQueue.DEAD_LETTER if deadletter else None,
        receive_mode=(ServiceBusReceiveMode.RECEIVE_AND_DELETE if force else ServiceBusReceiveMode.PEEK_LOCK),
    )
    with receiver:
        total = 0
        while True:
            msgs = receiver.receive_messages(max_message_count=50)
            if not msgs:
                break
            # En RECEIVE_AND_DELETE los mensajes ya vienen eliminados.
            if not force:
                for msg in msgs:
                    receiver.complete_message(msg)
            total += len(msgs)
            print(f"[{display_name}] Eliminados {len(msgs)} mensajes del batch (force={force})")
    print(f"[{display_name}] Total eliminados: {total}")


def main() -> None:
    connection = os.environ.get("TEST_SERVICE_BUS_CONNECTION") or os.environ.get("SERVICE_BUS_CONNECTION")
    if not connection:
        raise RuntimeError(
            "Define TEST_SERVICE_BUS_CONNECTION o SERVICE_BUS_CONNECTION antes de ejecutar el script"
        )

    # Flags: --deadletter, --force, --wait=<segundos>
    args = sys.argv[1:]
    use_deadletter = "--deadletter" in args
    use_force = "--force" in args
    wait_arg = next((a for a in args if a.startswith("--wait=")), None)
    wait_time = int(wait_arg.split("=", 1)[1]) if wait_arg else 5

    queue_args = [a for a in args if a not in ("--deadletter", "--force") and not a.startswith("--wait=")]
    queue_names = queue_args or DEFAULT_QUEUES

    with ServiceBusClient.from_connection_string(connection) as client:
        for queue_name in queue_names:
            _purge_queue(client, queue_name, deadletter=use_deadletter, force=use_force, wait_time=wait_time)


if __name__ == "__main__":
    main()
