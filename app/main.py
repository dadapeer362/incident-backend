from __future__ import annotations

import asyncio

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from app.models import (
    CreateIncidentRequest,
    Incident,
    IncidentSummary,
    TimelineEvent,
    TimelineEventType,
    UpdateIncidentStatusRequest,
    WSClientMessage,
)
from app.processor import HumanUpdateJob, IncidentLockManager, worker_loop
from app.store import IncidentStore
from app.websocket_manager import WebSocketRoomManager

app = FastAPI(title="Live Incident Room API", version="0.4")

store = IncidentStore()
ws_manager = WebSocketRoomManager()

processor_queue: asyncio.Queue[HumanUpdateJob] = asyncio.Queue()

MAX_WORKERS = 2
lock_manager = IncidentLockManager()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    for i in range(MAX_WORKERS):
        asyncio.create_task(
            worker_loop(
                worker_id=i + 1,
                queue=processor_queue,
                store=store,
                ws_manager=ws_manager,
                lock_manager=lock_manager,
            )
        )


@app.get("/health")
def health():
    return {"ok": True}


# --------- Incidents REST API ---------

@app.post("/incidents", response_model=Incident)
def create_incident(req: CreateIncidentRequest):
    inc = store.create_incident(title=req.title, severity=req.severity)
    return inc


@app.get("/incidents", response_model=list[IncidentSummary])
def list_incidents():
    return store.list_incidents()


@app.get("/incidents/{incident_id}", response_model=Incident)
def get_incident(incident_id: int):
    inc = store.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return inc


@app.patch("/incidents/{incident_id}/status", response_model=Incident)
async def update_incident_status(incident_id: int, req: UpdateIncidentStatusRequest):
    """
    NOTE: Made async so we can broadcast over websockets when resolved.
    """
    try:
        inc = store.update_status(incident_id, req.status)
    except KeyError:
        raise HTTPException(status_code=404, detail="Incident not found")

    # If resolved -> broadcast system message to all room clients
    if str(inc.status) == "resolved":
        system_event = TimelineEvent(
            incident_id=incident_id,
            type=TimelineEventType.system,
            payload={"message": "Incident resolved. Processing stopped."},
        )
        store.add_event(incident_id, system_event)

        await ws_manager.broadcast(
            incident_id,
            {"type": "timeline_event", "event": system_event.model_dump()},
        )

    return inc


# --------- WebSocket Incident Room ---------
@app.websocket("/ws/incidents/{incident_id}")
async def incident_room_ws(websocket: WebSocket, incident_id: int):
    inc = store.get_incident(incident_id)
    if not inc:
        await websocket.close(code=1008)
        return

    await ws_manager.connect(incident_id, websocket)

    try:
        await websocket.send_json(
            {
                "type": "initial_state",
                "incident": {
                    "id": inc.id,
                    "title": inc.title,
                    "severity": inc.severity,
                    "status": inc.status,
                    "created_at": inc.created_at.isoformat(),
                },
                "timeline": [e.model_dump(mode="json") for e in inc.timeline],
            }
        )

        while True:
            data = await websocket.receive_json()
            msg = WSClientMessage(**data)

            inc_latest = store.get_incident(incident_id)
            if not inc_latest:
                await websocket.send_json({"type": "error", "message": "Incident not found"})
                continue

            if str(inc_latest.status) == "resolved":
                await websocket.send_json(
                    {"type": "system", "message": "Incident is resolved. No new updates allowed."}
                )
                continue

            event = TimelineEvent(
                incident_id=incident_id,
                type=TimelineEventType.human_update,
                payload={"message": msg.message},
            )

            store.add_event(incident_id, event)

            await ws_manager.broadcast(
                incident_id,
                {"type": "timeline_event", "event": event.model_dump(mode="json")},
            )

            await processor_queue.put(
                HumanUpdateJob(
                    incident_id=incident_id,
                    human_event_id=event.event_id,
                    message=msg.message,
                )
            )

    except WebSocketDisconnect:
        await ws_manager.disconnect(incident_id, websocket)
    except Exception:
        await ws_manager.disconnect(incident_id, websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass