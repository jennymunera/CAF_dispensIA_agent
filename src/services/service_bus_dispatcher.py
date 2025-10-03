import json
import logging
from typing import Iterable

from azure.servicebus import ServiceBusClient, ServiceBusMessage

from src.models.dispensa_task import DispensaTaskModel

_LOGGER = logging.getLogger(__name__)


class ServiceBusDispatcher:
    def __init__(self, connection_string: str, queue_name: str) -> None:
        if not connection_string:
            raise ValueError("La cadena de conexión de Service Bus es obligatoria")
        if not queue_name:
            raise ValueError("El nombre de la cola de Service Bus es obligatorio")
        self._connection_string = connection_string
        self._queue_name = queue_name

    def send_tasks(self, tasks: Iterable[DispensaTaskModel]) -> int:
        task_list = list(tasks)
        if not task_list:
            _LOGGER.info("No se generaron tareas para enviar a Service Bus")
            return 0

        messages = [
            ServiceBusMessage(json.dumps(task.to_dict(), ensure_ascii=False))
            for task in task_list
        ]

        try:
            with ServiceBusClient.from_connection_string(self._connection_string) as client:
                sender = client.get_queue_sender(queue_name=self._queue_name)
                with sender:
                    sender.send_messages(messages)
            _LOGGER.info(
                "Se enviaron %s tareas a la cola '%s'",
                len(messages),
                self._queue_name,
            )
            return len(messages)
        except Exception:
            _LOGGER.exception(
                "Error enviando tareas a la cola de Service Bus '%s'",
                self._queue_name,
            )
            raise
