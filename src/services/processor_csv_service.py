import json
import logging
import pandas as pd
from azure.storage.blob import BlobServiceClient
import io
from datetime import datetime


def _normalize_date(raw: str) -> str:
    """
    Normaliza fechas ISO para obtener solo YYYY-MM-DD.
    Devuelve el valor original si no se puede parsear.
    """
    if not isinstance(raw, str):
        return raw
    text = raw.strip()
    if not text:
        return text

    candidates = [text, text.replace("Z", "+00:00")]
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate).date().isoformat()
        except ValueError:
            continue

    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return text

def process_dispensia_json_to_csv(        
    connection_string: str,
    container_name: str,
    source_json_blob: str,   # ej: basedocuments/{folder_name}/results/dispensia.json
    output_csv_blob: str     # ej: basedocuments/{folder_name}/results/dispensia.csv
) -> int:
    """
    Procesa el archivo dispensia.json y agrega una línea por cada dispensa (extrae los valores de 'value')
    al archivo dispensia.csv en Blob Storage.
    """
    try:
        logging.info(f"Inicio de la función: process_dispensia_json_to_csv para {source_json_blob}.")

        # Conexión a Blob Storage
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        container_client = blob_service_client.get_container_client(container_name)

        # 1️⃣ Descargar el JSON desde el blob
        json_blob_client = container_client.get_blob_client(source_json_blob)
        raw_data = json_blob_client.download_blob().readall().decode("utf-8").strip()
        json_content = json.loads(raw_data)

        # Validar que el JSON sea una lista de objetos
        if not isinstance(json_content, list):
            raise ValueError("El JSON debe ser una lista de objetos ([]) en el nivel raíz.")

        processed_rows = []

        # 2️⃣ Recorrer todos los objetos raíz
        for block in json_content:
            proceso = block.get("proceso", "")
            fuente_archivos = ", ".join(block.get("fuente_archivos", []))

            # Validar que contenga "dispensas"
            if "dispensas" not in block:
                logging.warning(f"Objeto sin clave 'dispensas': {block.keys()}")
                continue

            for dispensa in block["dispensas"]:
                row = {"proceso": proceso, "fuente_archivos": fuente_archivos}

                # Extraer todos los valores 'value' recursivamente
                def extract_values(prefix, data, result):
                    if isinstance(data, dict):
                        for key, val in data.items():
                            if isinstance(val, dict) and "value" in val:
                                result[f"{prefix}{key}"] = val["value"]
                            else:
                                extract_values(f"{prefix}{key}_", val, result)

                extract_values("", dispensa, row)

                fecha = row.get("fecha_extraccion")
                if isinstance(fecha, str) and fecha:
                    normalized = _normalize_date(fecha)
                    if normalized:
                        row["fecha_extraccion"] = normalized
                row.pop("id_dispensa", None)
                processed_rows.append(row)

        if not processed_rows:
            logging.warning("No se encontraron dispensas válidas en el JSON.")
            return 0

        # Crear DataFrame
        df_new = pd.DataFrame(processed_rows)
        logging.info(f"Se generaron {len(df_new)} registros a partir del JSON.")
        if "id_dispensa" in df_new.columns:
            df_new = df_new.drop(columns=["id_dispensa"])

        # 3️⃣ Descargar CSV existente si hay
        csv_blob_client = container_client.get_blob_client(output_csv_blob)
        try:
            existing_data = csv_blob_client.download_blob().readall()
            df_existing = pd.read_csv(io.BytesIO(existing_data))
            logging.info(f"CSV existente encontrado con {len(df_existing)} registros.")
            df_final = pd.concat([df_existing, df_new], ignore_index=True)
        except Exception:
            logging.info("No existía dispensia.csv, se creará uno nuevo.")
            df_final = df_new

        if "id_dispensa" in df_final.columns:
            df_final = df_final.drop(columns=["id_dispensa"])
        if "fecha_extraccion" in df_final.columns:
            df_final["fecha_extraccion"] = df_final["fecha_extraccion"].apply(_normalize_date)

        # 4️⃣ Guardar CSV actualizado
        output_stream = io.BytesIO()
        df_final.to_csv(output_stream, index=False, encoding="utf-8-sig")
        output_stream.seek(0)
        csv_blob_client.upload_blob(output_stream, overwrite=True)

        logging.info(f"✅ CSV actualizado correctamente: {container_name}/{output_csv_blob} - Total: {len(df_final)} registros.")
        return len(df_new)

    except Exception as e:
        logging.error(f"❌ Error en process_dispensia_json_to_csv: {str(e)}")
        raise
