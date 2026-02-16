"""WebSocket hub + notification poller."""

import asyncio
import json
from collections import defaultdict

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketDisconnect

from jarvis.auth.service import validate_token
from jarvis.db.connection import get_conn

router = APIRouter(tags=["ws"])


class WebSocketHub:
    def __init__(self) -> None:
        self._thread_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self._system_connections: set[WebSocket] = set()
        self._socket_threads: dict[WebSocket, set[str]] = defaultdict(set)
        self._socket_system: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self, websocket: WebSocket, thread_id: str) -> None:
        async with self._lock:
            self._thread_connections[thread_id].add(websocket)
            self._socket_threads[websocket].add(thread_id)

    async def unsubscribe(self, websocket: WebSocket, thread_id: str) -> None:
        async with self._lock:
            self._thread_connections[thread_id].discard(websocket)
            if not self._thread_connections[thread_id]:
                self._thread_connections.pop(thread_id, None)
            self._socket_threads[websocket].discard(thread_id)

    async def subscribe_system(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._system_connections.add(websocket)
            self._socket_system.add(websocket)

    async def unsubscribe_system(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._system_connections.discard(websocket)
            self._socket_system.discard(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            for thread_id in list(self._socket_threads.get(websocket, set())):
                self._thread_connections[thread_id].discard(websocket)
                if not self._thread_connections[thread_id]:
                    self._thread_connections.pop(thread_id, None)
            self._socket_threads.pop(websocket, None)
            self._system_connections.discard(websocket)
            self._socket_system.discard(websocket)

    async def broadcast_thread(self, thread_id: str, payload: dict[str, object]) -> None:
        async with self._lock:
            sockets = list(self._thread_connections.get(thread_id, set()))
        await _broadcast(sockets, payload)

    async def broadcast_system(self, payload: dict[str, object]) -> None:
        async with self._lock:
            sockets = list(self._system_connections)
        await _broadcast(sockets, payload)


async def _broadcast(sockets: list[WebSocket], payload: dict[str, object]) -> None:
    stale: list[WebSocket] = []
    for socket in sockets:
        try:
            await socket.send_json(payload)
        except Exception:
            stale.append(socket)
    if stale:
        for socket in stale:
            await hub.disconnect(socket)


hub = WebSocketHub()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "")
    with get_conn() as conn:
        auth_data = validate_token(conn, token)
    if auth_data is None:
        await websocket.close(code=1008)
        return
    user_id, role = auth_data

    await websocket.accept()
    await websocket.send_json({"type": "auth.ok", "user_id": user_id, "role": role})

    try:
        while True:
            data = await websocket.receive_json()
            action = str(data.get("action", ""))
            if action == "subscribe":
                thread_id = str(data.get("thread_id", "")).strip()
                if thread_id:
                    with get_conn() as conn:
                        row = conn.execute(
                            "SELECT user_id FROM threads WHERE id=? LIMIT 1", (thread_id,)
                        ).fetchone()
                    if row is None:
                        await websocket.send_json({"type": "error", "detail": "thread not found"})
                        continue
                    if role != "admin" and str(row["user_id"]) != user_id:
                        await websocket.send_json({"type": "error", "detail": "forbidden"})
                        continue
                    await hub.subscribe(websocket, thread_id)
                    await websocket.send_json({"type": "subscribed", "thread_id": thread_id})
            elif action == "unsubscribe":
                thread_id = str(data.get("thread_id", "")).strip()
                if thread_id:
                    await hub.unsubscribe(websocket, thread_id)
                    await websocket.send_json({"type": "unsubscribed", "thread_id": thread_id})
            elif action == "subscribe_system":
                await hub.subscribe_system(websocket)
                await websocket.send_json({"type": "subscribed.system"})
            else:
                await websocket.send_json({"type": "error", "detail": "unknown action"})
    except WebSocketDisconnect:
        await hub.disconnect(websocket)
    except Exception:
        await hub.disconnect(websocket)


async def notification_poller(stop: asyncio.Event) -> None:
    while not stop.is_set():
        await _poll_once()
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except TimeoutError:
            pass


async def _poll_once() -> None:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, thread_id, event_type, payload_json, created_at "
            "FROM web_notifications ORDER BY id ASC LIMIT 200"
        ).fetchall()
        if not rows:
            return
        ids = [int(row["id"]) for row in rows]

        for row in rows:
            thread_id = str(row["thread_id"])
            event_type = str(row["event_type"])
            raw_payload = str(row["payload_json"])
            try:
                payload = json.loads(raw_payload)
            except json.JSONDecodeError:
                payload = {"raw": raw_payload}

            # hydrate message payloads for immediate UI rendering
            if event_type == "message.new" and isinstance(payload, dict):
                message_id = payload.get("message_id")
                if isinstance(message_id, str):
                    message_row = conn.execute(
                        "SELECT id, role, content, created_at FROM messages WHERE id=? LIMIT 1",
                        (message_id,),
                    ).fetchone()
                    if message_row is not None:
                        payload["message"] = {
                            "id": str(message_row["id"]),
                            "role": str(message_row["role"]),
                            "content": str(message_row["content"]),
                            "created_at": str(message_row["created_at"]),
                        }

            envelope: dict[str, object] = {
                "type": event_type,
                "thread_id": thread_id,
                "created_at": str(row["created_at"]),
            }
            if isinstance(payload, dict):
                envelope.update(payload)
            else:
                envelope["payload"] = payload

            if event_type.startswith("system."):
                await hub.broadcast_system(envelope)
            else:
                await hub.broadcast_thread(thread_id, envelope)

        placeholders = ",".join("?" for _ in ids)
        conn.execute(f"DELETE FROM web_notifications WHERE id IN ({placeholders})", tuple(ids))


def start_notification_poller() -> tuple[asyncio.Task[None], asyncio.Event]:
    stop = asyncio.Event()
    task = asyncio.create_task(notification_poller(stop))
    return task, stop
