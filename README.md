# CAF_dispensIA_agent

Este repositorio contiene un único **Azure Function App** llamado `azfunc-MVP-DispensAI` que expone tres funciones (`router`, `dispensas_process` y `csv_global`). Cada handler se registra en `function_app.py` mediante el programming model v2 de Azure Functions, actuando como controller: recibe el trigger, valida parámetros obligatorios (mensajes en español) y delega en servicios especializados ubicados en `src/`.

> **Modelo v2**: no se crean carpetas individuales con `__init__.py` ni `function.json`. Los decoradores `@app.service_bus_queue_trigger`, `@app.route`, etc., generan la configuración automáticamente en tiempo de ejecución.

## Árbol del proyecto con descripciones
```
azfunc-MVP-DispensAI/
├── .funcignore                  # Exclusiones para despliegues de Azure Functions
├── .gitignore                   # Archivos y carpetas ignorados por Git
├── README.md                    # Documento de contexto, arquitectura y plan de trabajo
├── function_app.py              # Punto de entrada; registra handlers y compone servicios
├── host.json                    # Configuración global del Function App
├── local.settings.json          # Variables de entorno para desarrollo local
├── requirements.txt             # Dependencias de Python del Function App
├── src/
│   ├── interfaces/
│   │   └── blob_storage_interface.py    # Contrato abstracto para operaciones contra Blob Storage
│   ├── models/
│   │   ├── dispensa_task.py             # Modelo/validador para tareas individuales de procesamiento
│   │   └── queue_message.py             # Modelo/validador de mensajes de la cola inicial
│   ├── prompts/                         # Plantillas y prompts (pendiente de poblar)
│   ├── repositories/
│   │   └── blob_storage_repository.py   # Implementación del repositorio de blobs con Azure SDK
│   ├── services/
│   │   ├── blob_dispatcher.py           # Genera tareas por documento según la solicitud del router
│   │   ├── dispensas_processor.py       # Orquesta el flujo OpenAI para cada documento
│   │   ├── notifications_service.py     # Servicio existente para notificaciones externas
│   │   ├── openai_chained_service.py    # Encapsula la llamada de respuesta encadenada a OpenAI
│   │   ├── openai_client_factory.py     # Centraliza la autenticación y creación del cliente OpenAI
│   │   ├── openai_file_service.py       # Gestiona solicitudes con archivo (subida a OpenAI)
│   │   ├── openai_http_client.py        # Cliente HTTP que invoca las funciones internas de OpenAI
│   │   └── service_bus_dispatcher.py    # Envía mensajes de tareas a Service Bus
│   └── utils/
│       ├── blob_url_parser.py           # Extrae contenedor y nombre de blob a partir de la URL
│       ├── build_email_payload.py       # Utilidad previa para payloads de notificación
│       ├── content_type.py              # Define filename y content-type basados en la extensión
│       ├── prompt_loader.py             # Lee prompts desde archivos ubicados en `src/prompts`
│       └── response_parser.py           # Extrae texto de respuestas OpenAI y convierte a JSON
└── .vscode/
    └── settings.json            # Configuración del editor (VS Code)
```

## Detalle de la arquitectura
- **`function_app.py`**: capa de controllers. Allí se resuelven variables de entorno, se instancian repositorios/servicios y se definen los handlers HTTP y Service Bus. Los endpoints HTTP `request-with-file` y `chained-request` reutilizan la lógica de OpenAI y son consumidos internamente por `dispensas_process`.
- **Modelos (`src/models/`)**: encapsulan y validan los datos de entrada.
  - `QueueMessageModel` normaliza el mensaje de Service Bus inicial (proyecto, tipo de disparo, documentos, prompts, modelo).
  - `DispensaTaskModel` representa la tarea a nivel de documento que consumirá la función `dispensas_process`.
- **Interfaces y repositorios**: `BlobStorageInterface` define el contrato para trabajar con blobs y `BlobStorageRepository` implementa la lógica con `BlobServiceClient`, incluyendo subir texto/bytes, descargar y listar blobs con logs en español.
- **Servicios OpenAI**: `OpenAIClientFactory` abstrae la autenticación (API Key o Azure AD). `OpenAIFileService` porta la lógica de `request_with_file` (descargar blob, subir a OpenAI, obtener respuesta). `OpenAIChainedService` encapsula `previous_response_id` para continuar la conversación. `OpenAIHttpClient` llama a los endpoints HTTP internos. `DispensasProcessorService` usa este cliente HTTP para orquestar el flujo de respuestas. `BlobDispatcherService` fan-out de tareas según proyecto/documento. `notifications_service.py` permanece como servicio auxiliar preexistente.
- **Utilidades (`src/utils/`)**: funciones de apoyo reutilizables (parseo de URL de blob, determinación de content-type, extracción de texto/JSON de OpenAI, payloads de email).
- **Utilidades (`src/utils/`)**: funciones de apoyo reutilizables (parseo de URL de blob, determinación de content-type, extracción de texto/JSON de OpenAI, lectura de prompts desde archivos, payloads de email).

## Flujo de las funciones
1. **Router (`ServiceBusQueueTrigger`)**
   - Recibe un mensaje con `project_id`, `trigger_type`, documentos opcionales, modelo y prompts.
   - Se valida con `QueueMessageModel` (mensajes de error en español).
   - `BlobDispatcherService` determina qué blobs procesar: todos los del proyecto (`trigger_type = project`) o los documentos específicos (`trigger_type = document`).
   - Por cada blob genera una tarea (`DispensaTaskModel`) y la envía a la cola de trabajo que activará `dispensas_process`.

2. **Dispensas Process (`ServiceBusQueueTrigger`)**
   - Consume cada `DispensaTaskModel` de la cola.
   - `DispensasProcessorService` llama a los endpoints HTTP internos:
     1. `request-with-file`: prepara el archivo, lo sube a OpenAI y devuelve la respuesta inicial.
     2. `chained-request`: reutiliza el `response_id` anterior para obtener la respuesta encadenada.
     3. Convierte el contenido retornado a JSON (`response_parser.parse_json_response`).
   - Devuelve un diccionario con metadatos del documento, respuestas raw y JSON parseado listo para persistir o publicar.

   Los documentos de entrada por proyecto residen en `https://samvpdispensiacr.blob.core.windows.net/dispensia-documents/basedocuments/{project}/raw/` y las respuestas en JSON se deben almacenar en `https://samvpdispensiacr.blob.core.windows.net/dispensia-documents/basedocuments/{project}/results/`.

3. **CSV Global (`HTTP Trigger`, pendiente)**
   - Consolidará las respuestas generadas en un CSV fila a fila. Se implementará después de validar las dos funciones anteriores.

## Plan de trabajo
1. **Definir modelos** ✅ — `QueueMessageModel` y `DispensaTaskModel` creados.
2. **Servicios auxiliares** ✅ — `OpenAIClientFactory`, `OpenAIFileService`, `OpenAIChainedService`, `DispensasProcessorService`, `BlobDispatcherService`, `ServiceBusDispatcher` ya implementados.
3. **Repositorios/utilidades** ✅ — `BlobStorageRepository` extendido y helpers (`blob_url_parser`, `content_type`, `response_parser`) añadidos.
4. **Actualizar `function_app.py`** ✅ — Handlers `router` y `dispensas_process` configurados; `csv_global` se implementará más adelante.
5. **Configurar dependencias** 🔄 — `requirements.txt` actualizado con `azure-identity`, `azure-servicebus`, `openai`, `requests`; pendiente documentar ajustes finales en `local.settings.json` si cambian variables.
6. **Pruebas iniciales** — Simular mensajes de Service Bus con `azure-functions-core-tools`, validar logs, manejo de errores y resultados.

### Estado actual de las funciones 1 y 2
- **Handlers listos**: `router` y `dispensas_process` ya existen en `function_app.py` y delegan en los servicios correspondientes.
- **Endpoints HTTP**: `request-with-file` y `chained-request` expuestos como API reutilizando la lógica de OpenAI; `dispensas_process` los invoca mediante `OpenAIHttpClient`.
- **Servicios y utilidades portados**: flujo `request_with_file` y `chained_request` encapsulado en `openai_file_service.py` y `openai_chained_service.py`; fan-out y publicación en Service Bus resuelto con `blob_dispatcher.py` y `service_bus_dispatcher.py`.
- **Pendiente**:
  - Actualizar `local.settings.json` (o variables de aplicación) con `SERVICE_BUS_CONNECTION`, `ROUTER_QUEUE_NAME`, `PROCESS_QUEUE_NAME`, `DEFAULT_OPENAI_MODEL`, `DEFAULT_AGENT_PROMPT`, `DEFAULT_CHAINED_PROMPT` y credenciales de Blob/OpenAI.
  - Instalar dependencias (`pip install -r requirements.txt`).
  - Ejecutar pruebas locales: enviar un mensaje de ejemplo a `dispensas-router-in`, verificar generación de tareas y procesamiento completo, ajustar logging y manejo de errores según sea necesario.

## Variables de entorno claves
- `AZURE_STORAGE_CONNECTION_STRING`, `DEFAULT_BLOB_CONTAINER`: acceso a Blob Storage.
- `AZURE_OPENAI_ENDPOINT`, `USE_API_KEY`, `AZURE_OPENAI_API_KEY`: autenticación contra Azure OpenAI.
- `SERVICE_BUS_CONNECTION`: cadena de conexión con permisos para enviar y recibir en las colas.
- `ROUTER_QUEUE_NAME`, `PROCESS_QUEUE_NAME`: nombres de las colas (por defecto `dispensas-router-in` y `dispensas-process-in`).
- `DEFAULT_OPENAI_MODEL`, `DEFAULT_AGENT_PROMPT`, `DEFAULT_CHAINED_PROMPT`: valores por defecto utilizados cuando el mensaje de la cola no los especifica.
- `DEFAULT_AGENT_PROMPT_FILE`, `DEFAULT_CHAINED_PROMPT_FILE`: nombres de archivos (relativos a `src/prompts/`) desde los que se cargarán los prompts; si se omiten, se usan los valores inline anteriores como fallback.
- `INTERNAL_API_BASE_URL`: URL base del Function App para invocar los endpoints HTTP internos (por defecto `http://127.0.0.1:7071/api` en local).
- `INTERNAL_API_KEY`: clave opcional (`x-functions-key`) si los endpoints HTTP requieren autenticación (`FUNCTION` o `ADMIN`).

## Referencia cruzada
- Proyecto base: `/Users/jenny/Downloads/openai_responses_function_app`. De allí se portaron las funcionalidades `request_with_file` y `chained_request`, hoy encapsuladas en `openai_file_service.py` y `openai_chained_service.py`.

Este README se actualizará conforme se implementen los handlers y la función `csv_global`.
