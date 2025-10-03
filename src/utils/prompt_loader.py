from pathlib import Path
from typing import Optional


PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(relative_path: str) -> str:
    if not relative_path:
        raise ValueError("Se debe proporcionar la ruta relativa del prompt")

    prompt_path = PROMPTS_ROOT / relative_path

    if not prompt_path.exists():
        raise FileNotFoundError(f"No se encontró el prompt en '{prompt_path}'")

    return prompt_path.read_text(encoding="utf-8").strip()


def load_prompt_with_fallback(file_name: Optional[str], inline_prompt: Optional[str]) -> str:
    if file_name:
        return load_prompt(file_name)
    if inline_prompt:
        return inline_prompt
    raise ValueError("No se definió un prompt válido ni un archivo desde el cual cargarlo")
