import json
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """One process, in-memory. Fine for a single Uvicorn worker during development."""

    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

    async def connect(self, house_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._rooms.setdefault(house_id, set()).add(websocket)

    def disconnect(self, house_id: str, websocket: WebSocket) -> None:
        room = self._rooms.get(house_id)
        if not room:
            return
        room.discard(websocket)
        if not room:
            self._rooms.pop(house_id, None)

    async def broadcast(self, house_id: str, event: str, payload: dict[str, Any]) -> None:
        room = list(self._rooms.get(house_id, set()))
        if not room:
            return
        message = json.dumps({"event": event, "house_id": house_id, "data": payload})
        dead: list[WebSocket] = []
        for ws in room:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(house_id, ws)


manager = ConnectionManager()
