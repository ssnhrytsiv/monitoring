from __future__ import annotations

from pydantic import BaseModel


class PlanningButton(BaseModel):
    text: str
    callback: str
