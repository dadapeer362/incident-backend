from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Dict, Optional

from app.models import TimelineEvent, TimelineEventType


# ---------- Queue item schema ----------

@dataclass
class HumanUpdateJob:
    incident_id: int
    human_event_id: str
    message: str


# ---------- Per-incident lock manager ----------

class IncidentLockManager:
    def __init__(self):
        self._locks: dict[int, asyncio.Lock] = {}

    def get_lock(self, incident_id: int) -> asyncio.Lock:
        if incident_id not in self._locks:
            self._locks[incident_id] = asyncio.Lock()
        return self._locks[incident_id]



# ---------- Helpers for Stage A ----------

SERVICE_REGEX = re.compile(
    r"\b([a-zA-Z0-9_-]+-(service|api|worker))\b", re.IGNORECASE
)

KEYWORDS = [
    "error",
    "errors",
    "500",
    "timeout",
    "latency",
    "slow",
    "down",
    "crash",
    "restarted",
    "db",
    "database",
    "redis",
    "cpu",
    "memory",
    "hpa",
    "throttle",
]


def extract_service_name(text: str) -> Optional[str]:
    m = SERVICE_REGEX.search(text)
    if m:
        return m.group(1)
    return None


def extract_keywords(text: str) -> list[str]:
    lower = text.lower()
    found = []
    for k in KEYWORDS:
        if k in lower:
            found.append(k)
    return found


# ---------- Stage B fallback summary ----------

def fallback_summary(message: str, service: Optional[str], keywords: list[str]) -> str:
    base = message.strip()
    if len(base) > 140:
        base = base[:140].rstrip() + "..."

    if service and keywords:
        return f"Update about {service}. Signals: {', '.join(keywords[:6])}. Details: {base}"
    if service:
        return f"Update about {service}: {base}"
    if keywords:
        return f"Incident update signals: {', '.join(keywords[:6])}. Details: {base}"
    return f"Incident update: {base}"


# ---------- Worker loop ----------

async def worker_loop(worker_id: int, queue: asyncio.Queue, store, ws_manager, lock_manager):
    print(f"[worker {worker_id}] started")

    while True:
        job = await queue.get()

        try:
            incident_id = job.incident_id

            # Ensure ordering per incident
            async with lock_manager.get_lock(incident_id):

                inc = store.get_incident(incident_id)
                if not inc:
                    continue

                # Stop processing if resolved
                if str(inc.status) == "resolved":
                    continue

                # ---------------- Stage A: Enrichment ----------------
                tags = []
                msg_lower = job.message.lower()

                if "db" in msg_lower or "database" in msg_lower:
                    tags.append("database")
                if "timeout" in msg_lower:
                    tags.append("timeout")
                if "payment" in msg_lower or "checkout" in msg_lower:
                    tags.append("payments")
                if "latency" in msg_lower:
                    tags.append("latency")

                if not tags:
                    tags = ["general"]

                ai_tag_event = TimelineEvent(
                    incident_id=incident_id,
                    type=TimelineEventType.ai_tag,
                    payload={"tags": tags, "source_event_id": job.human_event_id},
                )

                store.add_event(incident_id, ai_tag_event)

                await ws_manager.broadcast(
                    incident_id,
                    {"type": "timeline_event", "event": ai_tag_event.model_dump(mode="json")},
                )

                # ---------------- Stage B: AI Summary ----------------
                await asyncio.sleep(1.5)

                summary = f"Summary: {job.message[:160]}"

                ai_summary_event = TimelineEvent(
                    incident_id=incident_id,
                    type=TimelineEventType.ai_summary,
                    payload={"summary": summary, "source_event_id": job.human_event_id},
                )

                store.add_event(incident_id, ai_summary_event)

                await ws_manager.broadcast(
                    incident_id,
                    {"type": "timeline_event", "event": ai_summary_event.model_dump(mode="json")},
                )

        except Exception as e:
            print(f"[worker {worker_id}] error:", repr(e))

        finally:
            queue.task_done()
