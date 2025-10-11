import json
import logging
import time
from typing import Iterable

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.exceptions import MessageSizeExceededError, ServiceBusConnectionError

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
        self._max_send_attempts = 3

    def send_tasks(self, tasks: Iterable[DispensaTaskModel]) -> int:
        task_list = list(tasks)
        if not task_list:
            _LOGGER.info("No se generaron tareas para enviar a Service Bus")
            return 0
        attempt = 1
        while attempt <= self._max_send_attempts:
            try:
                with ServiceBusClient.from_connection_string(self._connection_string) as client:
                    sender = client.get_queue_sender(queue_name=self._queue_name)
                    with sender:
                        batch = sender.create_message_batch()
                        batch_count = 0
                        for index, task in enumerate(task_list, start=1):
                            message = ServiceBusMessage(json.dumps(task.to_dict(), ensure_ascii=False))
                            try:
                                batch.add_message(message)
                                batch_count += 1
                            except MessageSizeExceededError:
                                if batch_count == 0:  # pragma: no cover - mensaje individual demasiado grande
                                    raise
                                sender.send_messages(batch)
                                _LOGGER.debug(
                                    "Lote de mensajes enviado a Service Bus con %s elementos (último índice: %s)",
                                    batch_count,
                                    index - 1,
                                )
                                batch = sender.create_message_batch()
                                batch_count = 0
                                try:
                                    batch.add_message(message)
                                    batch_count = 1
                                except MessageSizeExceededError:
                                    _LOGGER.error(
                                        "El mensaje para el documento '%s' excede el tamaño máximo de Service Bus",
                                        task.document_name,
                                    )
                                    raise

                        if batch_count > 0:
                            sender.send_messages(batch)
                            _LOGGER.debug(
                                "Lote final de mensajes enviado a Service Bus con %s elementos",
                                batch_count,
                            )
                _LOGGER.info(
                    "Se enviaron %s tareas a la cola '%s'",
                    len(task_list),
                    self._queue_name,
                )
                return len(task_list)
            except ServiceBusConnectionError as exc:
                if attempt >= self._max_send_attempts:
                    _LOGGER.exception(
                        "Error enviando tareas a la cola de Service Bus '%s' tras %s intentos",
                        self._queue_name,
                        self._max_send_attempts,
                    )
                    raise
                wait_time = min(5 * attempt, 30)
                _LOGGER.warning(
                    "Error de conexión al enviar tareas a '%s' (intento %s/%s). Reintentando en %s segundos",
                    self._queue_name,
                    attempt,
                    self._max_send_attempts,
                    wait_time,
                    exc_info=True,
                )
                time.sleep(wait_time)
                attempt += 1
            except Exception:
                _LOGGER.exception(
                    "Error enviando tareas a la cola de Service Bus '%s'",
                    self._queue_name,
                )
                raise
