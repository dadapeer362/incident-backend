from __future__ import annotations

import asyncio
from typing import Dict, Set

from fastapi import WebSocket


class WebSocketRoomManager:
    """
    Manages rooms:
      incident_id -> set of connected websockets
    """

    def __init__(self) -> None:
        self._rooms: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, incident_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            if incident_id not in self._rooms:
                self._rooms[incident_id] = set()
            self._rooms[incident_id].add(websocket)

    async def disconnect(self, incident_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            if incident_id in self._rooms:
                self._rooms[incident_id].discard(websocket)
                if not self._rooms[incident_id]:
                    del self._rooms[incident_id]

    async def broadcast(self, incident_id: int, message: dict) -> None:
        """
        Broadcast JSON message to all clients in the incident room.
        If any socket is dead, remove it.
        """
        async with self._lock:
            sockets = list(self._rooms.get(incident_id, set()))

        if not sockets:
            return

        dead: list[WebSocket] = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    if incident_id in self._rooms:
                        self._rooms[incident_id].discard(ws)
                if incident_id in self._rooms and not self._rooms[incident_id]:
                    del self._rooms[incident_id]
