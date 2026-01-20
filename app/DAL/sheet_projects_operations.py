"""
DAO for sheet_projects and sheet_project_archives.
Функціональний стиль: усі функції приймають зовнішній Session.
"""

import time
from dataclasses import dataclass
from typing import Optional, List

from sqlalchemy.orm import Session

from app.db import models as m


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


@dataclass
class SheetProjectRecord:
    project: str
    active_spreadsheet_id: Optional[str]
    active_title: Optional[str]
    updated_at: Optional[str]


@dataclass
class SheetProjectArchiveRecord:
    id: int
    project: str
    spreadsheet_id: str
    title: Optional[str]
    archived_at: Optional[str]

def get_active_sheet(db: Session, project: str) -> Optional[SheetProjectRecord]:
    row = db.query(m.SheetProject).filter(m.SheetProject.project == project).one_or_none()
    if not row:
        return None
    return SheetProjectRecord(
        project=row.project,
        active_spreadsheet_id=row.active_spreadsheet_id,
        active_title=row.active_title,
        updated_at=row.updated_at,
    )


def set_active_sheet(db: Session, project: str, spreadsheet_id: str, title: Optional[str]) -> None:
    """Встановлює активну таблицю для проєкту, попередню — в архів."""
    if not project or not spreadsheet_id:
        return
    now = _now_str()
    existing: Optional[m.SheetProject] = (
        db.query(m.SheetProject).filter(m.SheetProject.project == project).one_or_none()
    )
    if existing and existing.active_spreadsheet_id:
        db.add(
            m.SheetProjectArchive(
                project=project,
                spreadsheet_id=existing.active_spreadsheet_id,
                title=existing.active_title,
                archived_at=now,
            )
        )
    if existing:
        existing.active_spreadsheet_id = spreadsheet_id
        existing.active_title = title
        existing.updated_at = now
    else:
        db.add(
            m.SheetProject(
                project=project,
                active_spreadsheet_id=spreadsheet_id,
                active_title=title,
                updated_at=now,
            )
        )
    db.commit()


def list_projects(db: Session) -> List[str]:
    return list(db.query(m.SheetProject.project).distinct().scalars().all())


def list_archives(db: Session, project: Optional[str] = None) -> List[SheetProjectArchiveRecord]:
    q = db.query(m.SheetProjectArchive)
    if project:
        q = q.filter(m.SheetProjectArchive.project == project)
    rows = list(q.order_by(m.SheetProjectArchive.archived_at.desc(), m.SheetProjectArchive.id.desc()).all())
    return [
        SheetProjectArchiveRecord(
            id=int(r.id),
            project=r.project,
            spreadsheet_id=r.spreadsheet_id,
            title=r.title,
            archived_at=r.archived_at,
        )
        for r in rows
    ]
