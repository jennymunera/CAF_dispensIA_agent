# Plan de migración: mover `request_with_file` a `DispensasProcessorService`

Este documento describe el contexto actual del proyecto **azfunc-MVP-DispensAI**, detalla los cambios necesarios para ejecutar la lógica de `request_with_file` directamente dentro de `DispensasProcessorService`, y lista las validaciones requeridas después de implementar la migración. El objetivo es eliminar la invocación HTTP interna que hoy causa timeouts (503/504) al pasar por la ruta pública de Azure Functions.

---

## 1. Contexto del proyecto

### 1.1 Arquitectura actual
- **`function_app.py`** registra todas las funciones:
  - `request_with_file` (HTTP): recibe `prompt`, `model`, `blob_url`; descarga el PDF, lo sube a Azure OpenAI, espera la respuesta y devuelve el contenido. Actualmente se usa también como endpoint interno.
  - `chained_request` (HTTP).
  - `router` (Service Bus trigger): genera una tarea por cada PDF del proyecto.
  - `dispensas_process` (Service Bus trigger): procesa cada documento llamando al endpoint interno `request-with-file`, parsea el JSON y guarda los resultados.
  - `json_to_csv_request` (HTTP).
- **`src/services/openai_file_service.py`** implementa `send_request_with_file`, que contiene toda la lógica pesada (descargar blob, subir a OpenAI, leer respuesta, fallback de visión, almacenar resultado).
- **`src/services/dispensas_processor.py`**:
  - En `process(...)` invoca `OpenAIHttpClient.request_with_file(...)`, que hace un `POST` a `INTERNAL_API_BASE_URL/request-with-file`.
  - Maneja notificaciones, agregado de JSON y disparo del CSV.
- **`src/services/openai_http_client.py`** encapsula la llamada HTTP al endpoint interno (`requests.post`), con el timeout configurable `INTERNAL_API_TIMEOUT`.

### 1.2 Problemas detectados
- Cuando `dispensas_process` ejecuta documentos grandes, el `request-with-file` puede demorar >230s. Al invocarlo vía URL pública (`https://.../api/request-with-file`), el front-end de Azure Functions corta la conexión y retorna `504 Gateway Timeout`.
- Los reintentos sucesivos generan un `AttributeError` (`_requeue_document`) porque la versión desplegada aún lo invocaba.
- Esta arquitectura añade una dependencia innecesaria: el trigger llama a través de HTTP en vez de reutilizar directamente `OpenAIFileService`.

---

## 2. Objetivo de la migración

Mover la lógica de `request-with-file` para que se ejecute directamente dentro de `DispensasProcessorService.process(...)`. Así:
- Eliminamos la dependencia del endpoint HTTP interno.
- Evitamos los 503/504 causados por el front-end.
- Simplificamos el flujo: `dispensas_process` usará directamente la lógica de `OpenAIFileService`.

---

## 3. Cambios propuestos

1. **Actualizar `DispensasProcessorService`:**
   - Reemplazar la llamada a `self._http_client.request_with_file(...)` por una invocación directa al servicio `OpenAIFileService`.
   - Inyectar `OpenAIFileService` en el constructor de `DispensasProcessorService` (actualmente se inicializa en `function_app.py`, por lo que habrá que pasar la instancia como parámetro).
   - Ajustar `process(...)` para recibir la respuesta del método `send_request_with_file(...)` y seguir con el flujo normal (parsear JSON, persistir, etc.).
   - Eliminar cualquier referencia a `_requeue_document` (ya no se usa) y revisar los mecanismos de error.

2. **Eliminar la dependencia de `OpenAIHttpClient`:**
   - Una vez que `DispensasProcessorService` no use `OpenAIHttpClient`, evaluar si sigue siendo necesario. Si solo lo usaba `dispensas_process`, se puede remover su instancia en `function_app.py` (o dejarlo si otras funciones lo requieren).
   - Quitar de `local.settings.json` la variable `INTERNAL_API_BASE_URL` (o marcarla como obsoleta si otras piezas la siguen usando).
   - Actualizar `requirements` o archivos relacionados si `openai_http_client` ya no se usa.

3. **Refactorizar `request_with_file` (HTTP):**
   - Opcional: mantener el endpoint HTTP para usos externos o transformarlo en un wrapper ligero que llame al mismo método directo.
   - Si se mantiene, el HTTP debería reutilizar la misma función recién incorporada (sin duplicar lógica).
   - Documentar el cambio (por ejemplo, que ahora `request_with_file` HTTP comparte la lógica con `DispensasProcessorService`).

4. **Actualizaciones adicionales:**
   - Revisar notificaciones: `self._notify_error` actualmente intenta reenviar documentos. Una vez que el flow sea directo, confirma que no quede ninguna referencia a `_requeue_document`.
   - Ajustar pruebas o scripts (`tests/router_dispatch_helper.py`) si dependían del comportamiento anterior.

---

## 4. Pasos para la implementación

1. **Inyección de dependencias:**
   - Editar `function_app.py` para pasar `openai_file_service` al constructor de `DispensasProcessorService`.
   - Modificar la firma de `DispensasProcessorService.__init__` para recibirlo y guardarlo como miembro (`self._openai_file_service`).

2. **Actualizar `process(...)`:**
   - Reemplazar:
     ```python
     initial_response = self._http_client.request_with_file(...)
     ```
     por:
     ```python
     initial_response = self._openai_file_service.send_request_with_file(...)
     ```
   - El método `send_request_with_file` ya devuelve `{"response_id": ..., "content": ...}`. El resto del flujo (parsear, persistir) puede quedarse igual.
   - Al remover la llamada HTTP, se puede eliminar `OpenAIHttpClient` si ninguna otra función lo usa (verificar `DispensasProcessorService` y archivos relacionados).

3. **Limpiar dependencias obsoletas:**
   - Si `OpenAIHttpClient` queda sin uso, eliminar su import, su clase y cualquier referencia en `requirements` o inicializaciones.
   - Ajustar `local.settings.json` y los App Settings en Azure (remover `INTERNAL_API_BASE_URL`, o dejar comentario indicando que ya no se usa).

4. **Actualizar `request_with_file` HTTP (opcional):**
   - Si quieres conservar el endpoint para pruebas externas, puedes hacer que llame a `openai_file_service.send_request_with_file(...)` de forma directa (sin pasar por `DispensasProcessorService`).

5. **Probar localmente:**
   - `func start` y ejecuta un proyecto con `tests/router_dispatch_helper.py` para asegurar que:
     - Se procesa cada documento.
     - No hay timeouts ni errores por `_requeue_document`.
     - Se generan los JSON y el CSV como antes.
   - Verifica que las notificaciones `ERROR_FINALLY_PROCESS` sólo salgan cuando realmente hay fallos (cambia la habilidad de reintento si hiciste nuevos ajustes).

6. **Actualizar deploy y documentación:**
   - Refresca `deploy.sh` si removiste variables.
  - Cambia `README` o cualquier doc que mencione `INTERNAL_API_BASE_URL`.
  - Ejecuta `./deploy.sh ...` para subir la versión final y asegurarte de que no hay referencias a la URL interna.

---

## 5. Validaciones posteriores

1. **Pruebas funcionales:**
   - Procesar un proyecto chico (2-3 PDFs) y verificar:
     - Los JSON aparecen en `basedocuments/<project>/results/dispensas/`.
     - `dispensas_results.json` se actualiza con las entradas nuevas.
     - Cuando se completa todo el proyecto, se emite `SUCCESS_FINALLY_PROCESS` y el CSV (`FILENAME_CSV`) crece.
   - Confirmar que, ante una falla (por ejemplo, provocar un error en OpenAI), se emite una sola notificación `ERROR_FINALLY_PROCESS`.

2. **Logs y monitoreo:**
   - Revisar `Log stream` en Azure para confirmar que ya no aparecen 503/504 ni referencias a `_requeue_document`.
   - Validar que la Function App no necesita `INTERNAL_API_BASE_URL` ni `INTERNAL_API_TIMEOUT`.

3. **Tests auxiliares:**
   - `tests/router_dispatch_helper.py`: verificar que siga propagando mensajes a la cola y que los delays inter-documento siguen funcionando.
   - `tests/purge_queue.py`: limpiar colas después del test masivo para evitar backlog.

4. **Duración por documento:**
   - Aunque seguimos procesando cada PDF secuencialmente, ahora el tiempo total no se ve limitado por el front-end. Registra la duración promedio para planificar tiempos de corrida en producción.

5. **Sincronización con despliegue:**
   - Tras `git commit` y `git push`, ejecutar `./deploy.sh ...` para sincronizar en Azure.
   - Verificar que `Application Settings` no tenga la URL interna obsoleta.

---

## 6. Futuras mejoras (opcional)

- Si necesitas monitoreo más completo o control explícito de reintentos, considera migrar a Durable Functions (starter → orchestrator → activity).  
- Incorporar métricas adicionales (tiempo por documento, número de reintentos) para alimentar alertas o dashboards.  
- Ajustar el orquestador del helper (`tests/router_dispatch_helper.py`) para que consulte el estado del proyecto antes de lanzar el siguiente (esto ya está en discusión con el equipo).

---

## 7. Resumen

Esta migración reemplaza la llamada HTTP interna por una invocación directa a `OpenAIFileService`. Es la forma más rápida de eliminar los timeouts 503/504 y simplificar el pipeline. Tras aplicar los cambios, valida el flujo completo (JSON, agregado, CSV y notificaciones) tanto en local como en el entorno de Azure antes de dar por finalizada la tarea.

