"""Normalized issue representation used by the orchestrator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BlockerRef:
    """Reference to a blocking issue."""

    id: str | None = None
    identifier: str | None = None
    state: str | None = None


@dataclass
class Issue:
    """Normalized issue record used by orchestration, prompt rendering, and observability."""

    id: str | None = None
    identifier: str | None = None
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    state: str | None = None
    branch_name: str | None = None
    url: str | None = None
    assignee_id: str | None = None
    labels: list[str] = field(default_factory=list)
    blocked_by: list[BlockerRef] = field(default_factory=list)
    assigned_to_worker: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def label_names(self) -> list[str]:
        return self.labels

    def to_template_dict(self) -> dict:
        """Convert to a dict suitable for Jinja2 template rendering."""
        return {
            "id": self.id,
            "identifier": self.identifier,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "state": self.state,
            "branch_name": self.branch_name,
            "url": self.url,
            "assignee_id": self.assignee_id,
            "labels": ", ".join(self.labels) if self.labels else "",
            "blocked_by": [
                {"id": b.id, "identifier": b.identifier, "state": b.state}
                for b in self.blocked_by
            ],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
