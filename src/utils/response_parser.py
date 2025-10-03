import json
from typing import Any


def extract_response_text(response: Any) -> str:
    if not hasattr(response, "output"):
        raise ValueError("La respuesta de OpenAI no contiene el atributo 'output'")

    for item in response.output:
        item_type = getattr(item, "type", None)
        content = getattr(item, "content", None)
        if item_type == "message" and content:
            first_entry = content[0]
            text = getattr(first_entry, "text", None)
            if text:
                return text

    raise ValueError("No se encontró contenido en la respuesta de OpenAI")


def parse_json_response(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("El contenido devuelto por OpenAI no tiene formato JSON válido") from exc
