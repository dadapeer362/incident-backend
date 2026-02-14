from __future__ import annotations

from threading import Lock
from typing import Dict, List, Optional

from app.models import (
    Incident,
    IncidentStatus,
    IncidentSummary,
    Severity,
    TimelineEvent,
    TimelineEventType,
)


class IncidentStore:
    """
    In-memory store.
    Safe enough for local dev / interview style.
    Not for production (we'll replace with DB later).
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = 1
        self._incidents: Dict[int, Incident] = {}

    def create_incident(self, title: str, severity: Severity) -> Incident:
        with self._lock:
            incident_id = self._next_id
            self._next_id += 1

            inc = Incident(id=incident_id, title=title, severity=severity)

            # add timeline event: system created
            inc.timeline.append(
                TimelineEvent(
                    incident_id=incident_id,
                    type=TimelineEventType.system,
                    payload={"message": f"Incident created: {title} ({severity})"},
                )
            )

            self._incidents[incident_id] = inc
            return inc

    def list_incidents(self) -> List[IncidentSummary]:
        with self._lock:
            items = list(self._incidents.values())

        # return lightweight summaries
        return [
            IncidentSummary(
                id=i.id,
                title=i.title,
                severity=i.severity,
                status=i.status,
                created_at=i.created_at,
            )
            for i in items
        ]

    def get_incident(self, incident_id: int) -> Optional[Incident]:
        with self._lock:
            return self._incidents.get(incident_id)

    def add_event(self, incident_id: int, event: TimelineEvent) -> Incident:
        with self._lock:
            inc = self._incidents.get(incident_id)
            if not inc:
                raise KeyError("Incident not found")

            inc.timeline.append(event)
            return inc

    def update_status(self, incident_id: int, new_status: IncidentStatus) -> Incident:
        with self._lock:
            inc = self._incidents.get(incident_id)
            if not inc:
                raise KeyError("Incident not found")

            old_status = inc.status
            inc.status = new_status

            inc.timeline.append(
                TimelineEvent(
                    incident_id=incident_id,
                    type=TimelineEventType.status_change,
                    payload={
                        "from": old_status,
                        "to": new_status,
                    },
                )
            )

            return inc
