# CAF_dispensIA_agent

Function App que procesa documentos de dispensas del Banco CAF reutilizando Azure Functions y Azure OpenAI. Trabajamos con el programming model v2, por lo que todas las funciones se registran en `function_app.py` y comparten el paquete `src/` para la lógica de negocio.

> Modelo v2: no generamos carpetas por función ni `function.json` manuales; los decoradores (`@app.route`, `@app.service_bus_queue_trigger`, etc.) producen la configuración durante el build/despliegue.

## Árbol del proyecto
```
azfunc-MVP-DispensAI/
├── .funcignore                     # Archivos a excluir en despliegues de Functions
├── .gitignore                      # Ignorados por git
├── README.md                       # Este documento de arquitectura y flujo
├── function_app.py                 # Controllers Azure Functions (HTTP + Service Bus)
├── host.json                       # Config global del runtime
├── local.settings.json             # Variables locales (no se versiona en producción)
├── requirements.txt                # Dependencias Python
├── src/
│   ├── interfaces/
│   │   └── blob_storage_interface.py    # Contrato para repositorios de Blob
│   ├── models/
│   │   ├── dispensa_task.py             # Modelo de tareas individuales (Service Bus)
│   │   └── queue_message.py             # Modelo del mensaje de orquestación inicial
│   ├── prompts/
│   │   ├── agente_clasificador.txt      # Prompt del agente validador/taxonomía
│   │   └── agente_extractor.txt         # Prompt del agente extractor de dispensas
│   ├── repositories/
│   │   └── blob_storage_repository.py   # Implementación del repositorio Azure Blob
│   ├── services/
│   │   ├── blob_dispatcher.py           # Normaliza rutas raw/ y genera DispensaTaskModel
│   │   ├── dispensas_processor.py       # Invoca APIs internas y guarda resultados en results/
│   │   ├── notifications_service.py     # Cliente HTTP para notificaciones externas
│   │   ├── openai_chained_service.py    # Lógica original de chained_request
│   │   ├── openai_client_factory.py     # Crea clientes OpenAI (API Key / AAD)
│   │   ├── openai_file_service.py       # Lógica original de request_with_file
│   │   ├── openai_http_client.py        # Invoca endpoints internos vía HTTP
│   │   └── service_bus_dispatcher.py    # Envía lotes de tareas a la cola de proceso
│   └── utils/
│       ├── blob_url_parser.py           # Extrae contenedor/blob de URLs completas
│       ├── build_email_payload.py       # Helper legado para notificaciones
│       ├── content_type.py              # Determina filename + content-type según extensión
│       ├── prompt_loader.py             # Lee prompts desde archivos con fallback
│       └── response_parser.py           # Extrae texto y parsea JSON de respuestas OpenAI
└── .vscode/
    └── settings.json                   # Configuración recomendada para VS Code
```

## Funciones disponibles
1. **`request-with-file`** (`HTTP`, anónima por defecto)
   - Body: `{ prompt, model, blob_url | file_link }`.
   - Descarga el documento desde Blob Storage, lo sube a Azure OpenAI y devuelve `{response_id, content}` con la respuesta inicial del modelo.
2. **`chained-request`** (`HTTP`)
   - Body: `{ prompt, model, previous_response_id }`.
   - Reutiliza el `response_id` previo para obtener la respuesta encadenada.
3. **`router`** (`ServiceBusQueueTrigger` sobre `dispensas-router-in`)
   - Valida `QueueMessageModel`, detecta los blobs a procesar (prefijo `basedocuments/{project}/raw/`) y publica tareas individuales en `dispensas-process-in`.
4. **`dispensas_process`** (`ServiceBusQueueTrigger` sobre `dispensas-process-in`)
   - Consume `DispensaTaskModel`, invoca `request-with-file` (el flujo encadenado queda inactivo por ahora), parsea el JSON final y lo persiste en `basedocuments/{project}/results/{documento}.json`.
5. **`csv_global`** — **pendiente**: se implementará cuando consolidemos todos los JSON en un CSV maestro.

## Flujo end-to-end
1. **Mensaje de orquestación**
   - Un Service Bus message incluye `project_id`, `trigger_type` (`project | document`), lista de documentos opcional y overrides de modelo/prompts.
   - `QueueMessageModel` valida los campos y normaliza strings.
   - `BlobDispatcherService` arma el prefijo `basedocuments/{project}/raw/`, lista los blobs o normaliza los nombres solicitados y genera un `DispensaTaskModel` por archivo.
   - `ServiceBusDispatcher` envía cada tarea a `dispensas-process-in`.
2. **Procesamiento por documento**
   - `DispensasProcessorService` recibe el task, llama `request-with-file` y `chained-request`, convierte el output a JSON (`parsed_json`) y lo guarda en `basedocuments/{project}/results/{documento}.json`.
   - El método `process` devuelve un diccionario con metadatos del proyecto/documento, las respuestas intermedias y el JSON final listo para pasos posteriores (notificaciones, agregados, etc.).
3. **Consolidación (por hacer)**
   - El flujo actual solo persiste los JSON individuales. La función `csv_global` tomará esos archivos de `results/` y los concatenará en un CSV fila a fila.

## Rutas de almacenamiento
- **Entrada**: `https://samvpdispensiacr.blob.core.windows.net/dispensia-documents/basedocuments/{project}/raw/`
- **Salida**:  `https://samvpdispensiacr.blob.core.windows.net/dispensia-documents/basedocuments/{project}/results/`

`BlobDispatcherService` y `DispensasProcessorService` parametrizan estos paths con las variables `DOCUMENTS_BASE_PATH`, `RAW_DOCUMENTS_FOLDER` y `RESULTS_FOLDER` para cubrir otros escenarios (por defecto `basedocuments`, `raw`, `results`).

## Servicios y utilidades clave
- `OpenAIClientFactory`: crea instancias del SDK OpenAI autenticadas con API Key o Azure AD.
- `OpenAIFileService` / `OpenAIChainedService`: lógica portada desde el proyecto original (`request_with_file` y `chained_request`). Actualmente `OpenAIFileService` aplica fallback multimodal y persiste resultados; `chained_request` permanece disponible pero no se usa en el flujo automático.
- `OpenAIHttpClient`: encapsula las llamadas HTTP internas y maneja `x-functions-key` si se protege el endpoint.
- `BlobDispatcherService`: normaliza rutas, lista blobs y crea tareas `DispensaTaskModel`.
- `DispensasProcessorService`: orquesta el flujo, parsea el resultado y lo guarda en Blob Storage.
- `ServiceBusDispatcher`: publica mensajes en la cola de procesamiento.
- `prompt_loader`: carga prompts desde `src/prompts/*.txt` y permite fallback a variables de entorno.
- `notifications_service` y `build_email_payload`: utilidades existentes para futuras notificaciones externas.

## Variables de entorno (local/app settings)
| Clave | Descripción |
| --- | --- |
| `AzureWebJobsStorage` | Storage interno del runtime (Azurite o cuenta real). |
| `FUNCTIONS_WORKER_RUNTIME` | Mantener en `python`. |
| `AZURE_STORAGE_CONNECTION_STRING` | Conexión al Storage que contiene los documentos. |
| `DEFAULT_BLOB_CONTAINER` | Por defecto `dispensia-documents`. |
| `SERVICE_BUS_CONNECTION` | Conexión con permisos `Send/Listen`. |
| `ROUTER_QUEUE_NAME`, `PROCESS_QUEUE_NAME` | Colas de entrada y procesamiento (`dispensas-router-in`, `dispensas-process-in`). |
| `AZURE_OPENAI_ENDPOINT`, `USE_API_KEY`, `AZURE_OPENAI_API_KEY` | Credenciales de Azure OpenAI. |
| `DEFAULT_OPENAI_MODEL` | Modelo por defecto si el mensaje no lo define. |
| `DEFAULT_AGENT_PROMPT_FILE`, `DEFAULT_CHAINED_PROMPT_FILE` | Archivos relativos a `src/prompts/` (fallbacks inline: `DEFAULT_AGENT_PROMPT`, `DEFAULT_CHAINED_PROMPT`). |
| `INTERNAL_API_BASE_URL` | URL del propio Function App para invocar los endpoints HTTP (`http://127.0.0.1:7071/api` en local, `https://<app>.azurewebsites.net/api` en Azure). |
| `INTERNAL_API_KEY` | Function key (`x-functions-key`) si se protege el endpoint HTTP. |
| `DOCUMENTS_BASE_PATH`, `RAW_DOCUMENTS_FOLDER`, `RESULTS_FOLDER` | Segmentos de path para raw y results (defaults `basedocuments`, `raw`, `results`). |

## Plan y estado
1. **Modelos** ✅ — `QueueMessageModel` y `DispensaTaskModel` validados y localizados en `src/models/`.
2. **Servicios auxiliares** ✅ — Logic de OpenAI, dispatcher de blobs, cliente HTTP y repositorio de Storage implementados.
3. **Utilidades y prompts** ✅ — Helpers (`blob_url_parser`, `prompt_loader`, etc.) + prompts base en `src/prompts/`.
4. **Handlers** ✅ — `router`, `dispensas_process`, `request-with-file`, `chained-request` activos; `csv_global` aún por desarrollar.
5. **Config/Deploy** 🔄 — `requirements.txt` actualizado (`azure-servicebus`, `openai`, `azure-identity`, `requests`). Falta documentar la función CSV y la persistencia adicional si aplica.
6. **Pruebas** — Ejecutar `func start`, enviar un mensaje de ejemplo a `dispensas-router-in` y confirmar que los JSON terminan en `results/`. (Pendiente de automatización).

## Próximos pasos
1. Implementar `csv_global` para recorrer `results/` y generar el CSV maestro.
2. Definir persistencia adicional (ej. notificación, índice, almacenamiento en base de datos) reutilizando `notifications_service` si aplica.
3. Automatizar pruebas end-to-end y/o agregar pipelines de despliegue.

## Referencia
- Proyecto original: `/Users/jenny/Downloads/openai_responses_function_app` — fuente de `request_with_file` y `chained_request`.
- Variables sensibles (keys de Storage, Service Bus, OpenAI) deben rotarse/gestionarse mediante App Settings o Key Vault antes de desplegar.
