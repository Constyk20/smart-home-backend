from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.core.realtime import manager
from app.core.security import decode_access_token
from app.services.auth_service import get_user_by_id
from app.services.house_service import get_house_by_id

router = APIRouter()


@router.websocket("/ws/houses/{house_id}")
async def house_updates(
    websocket: WebSocket,
    house_id: str,
    token: str = Query(...),
):
    user_id = decode_access_token(token)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = await get_user_by_id(user_id)
    if not user or not user.get("is_active", False):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        await get_house_by_id(house_id, user_id)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(house_id, websocket)
    try:
        await websocket.send_json({"event": "connected", "house_id": house_id, "data": {}})
        while True:
            # Client messages are ignored for now. The server pushes events.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(house_id, websocket)
