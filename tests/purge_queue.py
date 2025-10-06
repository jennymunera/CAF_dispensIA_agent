# Script para purgar una cola de Azure Service Bus
"""Uso: TEST_SERVICE_BUS_CONNECTION='...' python purge_queue.py [queue]"""
import os
import sys

from azure.servicebus import ServiceBusClient


def main() -> None:
    connection = os.environ.get("TEST_SERVICE_BUS_CONNECTION") or os.environ.get("SERVICE_BUS_CONNECTION")
    if not connection:
        raise RuntimeError(
            "Define TEST_SERVICE_BUS_CONNECTION o SERVICE_BUS_CONNECTION antes de ejecutar el script"
        )

    queue_name = sys.argv[1] if len(sys.argv) > 1 else "dispensas-router-in"

    with ServiceBusClient.from_connection_string(connection) as client:
        receiver = client.get_queue_receiver(queue_name, max_wait_time=5)
        with receiver:
            total = 0
            while True:
                msgs = receiver.receive_messages(max_message_count=50)
                if not msgs:
                    break
                receiver.complete_message_batch(msgs)
                total += len(msgs)
                print(f"Eliminados {len(msgs)} mensajes del batch")
    print(f"Total eliminados de '{queue_name}': {total}")


if __name__ == "__main__":
    main()
