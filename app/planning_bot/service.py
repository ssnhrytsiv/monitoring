from __future__ import annotations

from app.planning_bot.models import PlanningButton


def default_buttons() -> list[PlanningButton]:
    return [
        PlanningButton(text="📋 Планування", callback="planning:start"),
    ]
