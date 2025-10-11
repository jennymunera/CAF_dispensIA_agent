import json
import re
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)


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
    """
    Intenta parsear la respuesta de OpenAI como JSON usando múltiples estrategias.
    
    Args:
        text: El texto de respuesta de OpenAI
        
    Returns:
        El objeto JSON parseado
        
    Raises:
        ValueError: Si no se puede extraer JSON válido de la respuesta
    """
    if not text or not text.strip():
        raise ValueError("El contenido devuelto por OpenAI está vacío")
    
    # Estrategia 1: Intentar parsear directamente
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        _LOGGER.debug("Fallo el parsing directo de JSON, intentando estrategias alternativas")
    
    # Estrategia 2: Buscar JSON entre bloques de código (objetos o listas)
    fenced_objects = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    fenced_arrays = re.findall(r'```(?:json)?\s*(\[.*?\])\s*```', text, re.DOTALL | re.IGNORECASE)
    for block in fenced_objects + fenced_arrays:
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue
    
    # Estrategia 3: Buscar el primer objeto JSON válido en el texto
    json_patterns = [
        r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Objetos JSON simples
        r'\{.*?\}',  # Cualquier cosa entre llaves
        r'\[.*?\]',  # Cualquier cosa entre corchetes (listas)
    ]
    
    for pattern in json_patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
    
    # Estrategia 4: Buscar líneas que contengan JSON
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if (line.startswith('{') and line.endswith('}')) or (line.startswith('[') and line.endswith(']')):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    
    # Estrategia 5: Intentar limpiar el texto y parsear
    cleaned_text = text.strip()
    # Remover posibles prefijos explicativos
    if '```' in cleaned_text:
        # Extraer contenido entre triple backticks
        parts = cleaned_text.split('```')
        for i, part in enumerate(parts):
            if i % 2 == 1:  # Contenido dentro de backticks
                try:
                    # Remover posible etiqueta de lenguaje
                    content = re.sub(r'^(json|JSON)\s*', '', part.strip())
                    return json.loads(content)
                except json.JSONDecodeError:
                    continue
    
    # Log del contenido problemático para debugging
    _LOGGER.warning("No se pudo extraer JSON válido de la respuesta de OpenAI. Contenido: %s", text[:500])
    
    raise ValueError("El contenido devuelto por OpenAI no tiene formato JSON válido")
