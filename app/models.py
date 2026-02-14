from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Severity(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class IncidentStatus(str, Enum):
    investigating = "investigating"
    monitoring = "monitoring"
    resolved = "resolved"


class TimelineEventType(str, Enum):
    human_update = "human_update"
    status_change = "status_change"
    ai_tag = "ai_tag"
    ai_summary = "ai_summary"
    system = "system"


class TimelineEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    incident_id: int
    type: TimelineEventType
    created_at: datetime = Field(default_factory=utc_now)

    # generic payload (for now)
    payload: Dict[str, Any] = Field(default_factory=dict)


class Incident(BaseModel):
    id: int
    title: str
    severity: Severity
    status: IncidentStatus = IncidentStatus.investigating
    created_at: datetime = Field(default_factory=utc_now)

    timeline: List[TimelineEvent] = Field(default_factory=list)


# ---------- Request/Response Schemas ----------

class CreateIncidentRequest(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    severity: Severity


class UpdateIncidentStatusRequest(BaseModel):
    status: IncidentStatus


class IncidentSummary(BaseModel):
    id: int
    title: str
    severity: Severity
    status: IncidentStatus
    created_at: datetime

class WSClientMessage(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
