"""
DAO for sheet_projects and sheet_project_archives.
Файл назвено за схемою <table>_operations.
"""

import time
from typing import Optional, List

from sqlalchemy.orm import Session

from app.admin_bot.db import models as m


def _now_str() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


class SheetProjectsDAO:
    def __init__(self, db: Session):
        self.db = db

    def get_active_sheet(self, project: str) -> Optional[m.SheetProject]:
        return self.db.query(m.SheetProject).filter(m.SheetProject.project == project).one_or_none()

    def set_active_sheet(self, project: str, spreadsheet_id: str, title: Optional[str]) -> None:
        """Встановлює активну таблицю для проєкту, попередню — в архів."""
        if not project or not spreadsheet_id:
            return
        now = _now_str()
        existing: Optional[m.SheetProject] = self.get_active_sheet(project)
        if existing and existing.active_spreadsheet_id:
            self.db.add(
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
            self.db.add(
                m.SheetProject(
                    project=project,
                    active_spreadsheet_id=spreadsheet_id,
                    active_title=title,
                    updated_at=now,
                )
            )
        self.db.commit()

    def list_projects(self) -> List[str]:
        return list(self.db.query(m.SheetProject.project).distinct().scalars().all())

    def list_archives(self, project: Optional[str] = None) -> List[m.SheetProjectArchive]:
        q = self.db.query(m.SheetProjectArchive)
        if project:
            q = q.filter(m.SheetProjectArchive.project == project)
        return list(q.order_by(m.SheetProjectArchive.archived_at.desc(), m.SheetProjectArchive.id.desc()).all())


# Функціональні обгортки для сумісності
def get_active_sheet(db: Session, project: str) -> Optional[m.SheetProject]:
    return SheetProjectsDAO(db).get_active_sheet(project)


def set_active_sheet(db: Session, project: str, spreadsheet_id: str, title: Optional[str]) -> None:
    return SheetProjectsDAO(db).set_active_sheet(project, spreadsheet_id, title)


def list_projects(db: Session) -> List[str]:
    return SheetProjectsDAO(db).list_projects()


def list_archives(db: Session, project: Optional[str] = None) -> List[m.SheetProjectArchive]:
    return SheetProjectsDAO(db).list_archives(project)
