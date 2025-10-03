from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


def _clean_list(items: Optional[List[str]]) -> List[str]:
    if not items:
        return []
    return [item for item in (s.strip() for s in items) if item]


@dataclass
class QueueMessageModel:
    project_id: str
    trigger_type: str
    documents: List[str] = field(default_factory=list)
    model: Optional[str] = None
    agent_prompt: Optional[str] = None
    chained_prompt: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "QueueMessageModel":
        if not isinstance(data, dict):
            raise ValueError("El payload del mensaje de la cola debe ser un diccionario")

        project_id = (data.get("project_id") or "").strip()
        trigger_type = (data.get("trigger_type") or "").strip()

        if not project_id:
            raise ValueError("'project_id' es obligatorio en el mensaje de la cola")
        if not trigger_type:
            raise ValueError("'trigger_type' es obligatorio en el mensaje de la cola")

        documents = data.get("documents") or []
        if isinstance(documents, str):
            documents = [documents]
        if not isinstance(documents, list):
            raise ValueError("'documents' debe ser una lista o una cadena")

        model = (data.get("model") or None)
        agent_prompt = (data.get("agent_prompt") or None)
        chained_prompt = (data.get("chained_prompt") or None)

        return cls(
            project_id=project_id,
            trigger_type=trigger_type,
            documents=_clean_list(documents),
            model=model.strip() if isinstance(model, str) else model,
            agent_prompt=agent_prompt.strip() if isinstance(agent_prompt, str) else agent_prompt,
            chained_prompt=chained_prompt.strip() if isinstance(chained_prompt, str) else chained_prompt,
        )

    def require_documents(self) -> None:
        if not self.documents:
            raise ValueError("No se proporcionaron documentos para procesar")
