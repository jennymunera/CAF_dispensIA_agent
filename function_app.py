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
from src.services.openai_http_client import OpenAIHttpClient
from src.services.service_bus_dispatcher import ServiceBusDispatcher
from src.utils.prompt_loader import load_prompt_with_fallback


logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)

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
DOCUMENTS_BASE_PATH = os.getenv("DOCUMENTS_BASE_PATH", "basedocuments")
RAW_DOCUMENTS_FOLDER = os.getenv("RAW_DOCUMENTS_FOLDER", "raw")
RESULTS_FOLDER = os.getenv("RESULTS_FOLDER", "results")

INTERNAL_API_BASE_URL = os.getenv("INTERNAL_API_BASE_URL", "http://127.0.0.1:7071/api")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

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
openai_http_client = OpenAIHttpClient(
    base_url=INTERNAL_API_BASE_URL,
    function_key=INTERNAL_API_KEY,
)
dispensas_processor_service = DispensasProcessorService(
    http_client=openai_http_client,
    blob_repository=blob_repository,
    base_path=DOCUMENTS_BASE_PATH,
    results_folder=RESULTS_FOLDER,
)
blob_dispatcher_service = BlobDispatcherService(
    blob_repository,
    default_model=DEFAULT_OPENAI_MODEL,
    default_agent_prompt=DEFAULT_AGENT_PROMPT,
    default_chained_prompt=DEFAULT_CHAINED_PROMPT,
    base_path=DOCUMENTS_BASE_PATH,
    raw_folder=RAW_DOCUMENTS_FOLDER,
)
service_bus_dispatcher = ServiceBusDispatcher(
    connection_string=SERVICE_BUS_CONNECTION_STRING,
    queue_name=PROCESS_QUEUE_NAME,
)

logger = logging.getLogger(__name__)


@app.function_name(name="request_with_file")
@app.route(route="request-with-file", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def request_with_file_http(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Procesando solicitud HTTP request-with-file")
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "El cuerpo de la petición debe ser un JSON válido"}),
            status_code=400,
            mimetype="application/json",
        )

    prompt = (payload.get("prompt") or "").strip()
    model = (payload.get("model") or "").strip()
    blob_url = (payload.get("blob_url") or payload.get("file_link") or "").strip()

    if not prompt:
        return func.HttpResponse(
            json.dumps({"error": "El campo 'prompt' es obligatorio"}),
            status_code=400,
            mimetype="application/json",
        )
    if not model:
        return func.HttpResponse(
            json.dumps({"error": "El campo 'model' es obligatorio"}),
            status_code=400,
            mimetype="application/json",
        )
    if not blob_url:
        return func.HttpResponse(
            json.dumps({"error": "Se debe especificar 'blob_url' o 'file_link'"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        result = openai_file_service.send_request_with_file(
            blob_url=blob_url,
            prompt=prompt,
            model=model,
        )
        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as exc:  # pragma: no cover - errores propagados como 500
        logger.exception("Error en request-with-file: %s", exc)
        return func.HttpResponse(
            json.dumps({"error": str(exc)}),
            status_code=500,
            mimetype="application/json",
        )


@app.function_name(name="chained_request")
@app.route(route="chained-request", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def chained_request_http(req: func.HttpRequest) -> func.HttpResponse:
    logger.info("Procesando solicitud HTTP chained-request")
    try:
        payload = req.get_json()
    except ValueError:
        return func.HttpResponse(
            json.dumps({"error": "El cuerpo de la petición debe ser un JSON válido"}),
            status_code=400,
            mimetype="application/json",
        )

    prompt = (payload.get("prompt") or "").strip()
    model = (payload.get("model") or "").strip()
    previous_response_id = (payload.get("previous_response_id") or "").strip()

    if not prompt:
        return func.HttpResponse(
            json.dumps({"error": "El campo 'prompt' es obligatorio"}),
            status_code=400,
            mimetype="application/json",
        )
    if not model:
        return func.HttpResponse(
            json.dumps({"error": "El campo 'model' es obligatorio"}),
            status_code=400,
            mimetype="application/json",
        )
    if not previous_response_id:
        return func.HttpResponse(
            json.dumps({"error": "El campo 'previous_response_id' es obligatorio"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        result = openai_chained_service.send_chained_request(
            model=model,
            prompt=prompt,
            previous_response_id=previous_response_id,
        )
        return func.HttpResponse(
            json.dumps(result, ensure_ascii=False),
            status_code=200,
            mimetype="application/json",
        )
    except Exception as exc:
        logger.exception("Error en chained-request: %s", exc)
        return func.HttpResponse(
            json.dumps({"error": str(exc)}),
            status_code=500,
            mimetype="application/json",
        )


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
