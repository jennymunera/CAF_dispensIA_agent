from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class DispensaTaskModel:
    project_id: str
    blob_url: str
    model: str
    agent_prompt: str
    chained_prompt: str
    document_name: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "DispensaTaskModel":
        if not isinstance(data, dict):
            raise ValueError("El payload de la tarea de dispensa debe ser un diccionario")

        project_id = (data.get("project_id") or "").strip()
        blob_url = (data.get("blob_url") or data.get("file_link") or "").strip()
        model = (data.get("model") or "").strip()
        agent_prompt = (data.get("agent_prompt") or "").strip()
        chained_prompt = (data.get("chained_prompt") or "").strip()
        document_name = (data.get("document_name") or None)

        if not project_id:
            raise ValueError("'project_id' es obligatorio en la tarea de dispensa")
        if not blob_url:
            raise ValueError("'blob_url' (o 'file_link') es obligatorio en la tarea de dispensa")
        if not model:
            raise ValueError("'model' es obligatorio en la tarea de dispensa")
        if not agent_prompt:
            raise ValueError("'agent_prompt' es obligatorio en la tarea de dispensa")
        if not chained_prompt:
            raise ValueError("'chained_prompt' es obligatorio en la tarea de dispensa")

        return cls(
            project_id=project_id,
            blob_url=blob_url,
            model=model,
            agent_prompt=agent_prompt,
            chained_prompt=chained_prompt,
            document_name=document_name.strip() if isinstance(document_name, str) else document_name,
        )

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "blob_url": self.blob_url,
            "model": self.model,
            "agent_prompt": self.agent_prompt,
            "chained_prompt": self.chained_prompt,
            "document_name": self.document_name,
        }
