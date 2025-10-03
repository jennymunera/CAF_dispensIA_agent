import json
import logging
import os

import azure.functions as func

from src.models.dispensa_task import DispensaTaskModel
from src.models.queue_message import QueueMessageModel
from src.repositories.blob_storage_repository import BlobStorageRepository
from src.services.blob_dispatcher import BlobDispatcherService
from src.services.dispensas_processor import DispensasProcessorService
from src.services.openai_chained_service import OpenAIChainedService
from src.services.openai_client_factory import OpenAIClientFactory
from src.services.openai_file_service import OpenAIFileService
from src.services.service_bus_dispatcher import ServiceBusDispatcher
from src.utils.prompt_loader import load_prompt_with_fallback

app = func.FunctionApp()

# Configuración de nombres y conexiones
ROUTER_QUEUE_NAME = os.getenv("ROUTER_QUEUE_NAME", "dispensas-router-in")
PROCESS_QUEUE_NAME = os.getenv("PROCESS_QUEUE_NAME", "dispensas-process-in")
SERVICE_BUS_CONNECTION_SETTING = "SERVICE_BUS_CONNECTION"
SERVICE_BUS_CONNECTION_STRING = os.getenv(SERVICE_BUS_CONNECTION_SETTING)

BLOB_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
DEFAULT_BLOB_CONTAINER = os.getenv("DEFAULT_BLOB_CONTAINER")

DEFAULT_OPENAI_MODEL = os.getenv("DEFAULT_OPENAI_MODEL")
DEFAULT_AGENT_PROMPT = load_prompt_with_fallback(
    os.getenv("DEFAULT_AGENT_PROMPT_FILE"),
    os.getenv("DEFAULT_AGENT_PROMPT"),
)
DEFAULT_CHAINED_PROMPT = load_prompt_with_fallback(
    os.getenv("DEFAULT_CHAINED_PROMPT_FILE"),
    os.getenv("DEFAULT_CHAINED_PROMPT"),
)

if not BLOB_CONNECTION_STRING:
    raise ValueError("La variable 'AZURE_STORAGE_CONNECTION_STRING' es obligatoria")
if not DEFAULT_BLOB_CONTAINER:
    raise ValueError("La variable 'DEFAULT_BLOB_CONTAINER' es obligatoria")
if not SERVICE_BUS_CONNECTION_STRING:
    raise ValueError("La variable 'SERVICE_BUS_CONNECTION' debe contener la cadena de conexión de Service Bus")

blob_repository = BlobStorageRepository(
    connection_string=BLOB_CONNECTION_STRING,
    default_container=DEFAULT_BLOB_CONTAINER,
)

openai_client_factory = OpenAIClientFactory()
openai_file_service = OpenAIFileService(blob_repository, openai_client_factory)
openai_chained_service = OpenAIChainedService(openai_client_factory)
dispensas_processor_service = DispensasProcessorService(openai_file_service, openai_chained_service)
blob_dispatcher_service = BlobDispatcherService(
    blob_repository,
    default_model=DEFAULT_OPENAI_MODEL,
    default_agent_prompt=DEFAULT_AGENT_PROMPT,
    default_chained_prompt=DEFAULT_CHAINED_PROMPT,
)
service_bus_dispatcher = ServiceBusDispatcher(
    connection_string=SERVICE_BUS_CONNECTION_STRING,
    queue_name=PROCESS_QUEUE_NAME,
)

logger = logging.getLogger(__name__)


@app.function_name(name="router")
@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name=ROUTER_QUEUE_NAME,
    connection=SERVICE_BUS_CONNECTION_SETTING,
)
def router(message: func.ServiceBusMessage) -> None:
    try:
        payload = message.get_body().decode("utf-8")
        data = json.loads(payload)
        queue_message = QueueMessageModel.from_dict(data)
    except ValueError as exc:
        logger.error("El mensaje recibido no es válido: %s", exc)
        raise

    try:
        tasks = blob_dispatcher_service.generate_tasks(queue_message)
    except Exception as exc:  # pragma: no cover - el runtime reintentará el mensaje
        logger.error(
            "Error generando tareas para el proyecto '%s': %s",
            queue_message.project_id,
            exc,
        )
        raise

    try:
        sent_count = service_bus_dispatcher.send_tasks(tasks)
        logger.info(
            "Se enviaron %s tareas a la cola de procesamiento para el proyecto '%s'",
            sent_count,
            queue_message.project_id,
        )
    except Exception as exc:
        logger.error("No se pudieron enviar las tareas a Service Bus: %s", exc)
        raise


@app.function_name(name="dispensas_process")
@app.service_bus_queue_trigger(
    arg_name="message",
    queue_name=PROCESS_QUEUE_NAME,
    connection=SERVICE_BUS_CONNECTION_SETTING,
)
def dispensas_process(message: func.ServiceBusMessage) -> None:
    try:
        payload = message.get_body().decode("utf-8")
        data = json.loads(payload)
        task = DispensaTaskModel.from_dict(data)
    except ValueError as exc:
        logger.error("La tarea recibida no es válida: %s", exc)
        raise

    result = dispensas_processor_service.process(task)
    logger.info(
        "Resultado procesado para el proyecto '%s' y documento '%s'",
        task.project_id,
        task.document_name,
    )
    logger.debug("Respuesta encadenada: %s", result["chained_response"])
    logger.debug("JSON parseado: %s", result["parsed_json"])
