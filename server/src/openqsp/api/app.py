"""FastAPI adapter for the durable OpenQSP messaging domain."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict

from openqsp.protocol import Message, normalize_callsign
from openqsp.protocol.errors import InvalidFieldError
from openqsp.server.core import ServerCore
from openqsp.storage import (
    AccountStore,
    IdempotencyConflictError,
    InvalidCredentialsError,
    MessageStore,
    StoredMessage,
)

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, str] | None = None,
    ):
        self.status, self.code, self.message, self.details = (
            status,
            code,
            message,
            details,
        )


class Login(BaseModel):
    callsign: str
    password: str


class Send(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str
    body: str


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class Signer:
    def __init__(self, secret: str, lifetime: int):
        self.secret, self.lifetime = secret.encode(), lifetime

    def sign(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return (
            _b64(raw) + "." + _b64(hmac.new(self.secret, raw, hashlib.sha256).digest())
        )

    def read(self, token: str) -> dict[str, Any]:
        try:
            encoded, signature = token.split(".")
            raw = _unb64(encoded)
            if not hmac.compare_digest(
                _unb64(signature), hmac.new(self.secret, raw, hashlib.sha256).digest()
            ):
                raise ValueError
            return json.loads(raw)
        except (ValueError, TypeError, json.JSONDecodeError):
            raise APIError(
                401, "invalid_token", "Invalid or expired access token."
            ) from None

    def access(self, callsign: str) -> str:
        return self.sign(
            {"kind": "access", "sub": callsign, "exp": int(time.time()) + self.lifetime}
        )

    def identity(self, token: str) -> str:
        data = self.read(token)
        if data.get("kind") != "access" or not isinstance(data.get("sub"), str):
            raise APIError(401, "invalid_token", "Invalid or expired access token.")
        try:
            expired = int(data.get("exp", 0)) < int(time.time())
        except (TypeError, ValueError):
            expired = True
        if expired:
            raise APIError(401, "invalid_token", "Invalid or expired access token.")
        return data["sub"]

    def cursor(self, callsign: str, sequence: int, kind: str) -> str:
        return self.sign({"kind": kind, "sub": callsign, "seq": sequence})

    def cursor_value(self, token: str, callsign: str, kind: str) -> int:
        try:
            data = self.read(token)
        except APIError:
            raise APIError(400, "invalid_request", "Invalid cursor.") from None
        if (
            data.get("kind") != kind
            or data.get("sub") != callsign
            or not isinstance(data.get("seq"), int)
            or data["seq"] < 0
        ):
            raise APIError(400, "invalid_request", "Invalid cursor.")
        return data["seq"]


class EventHub:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = defaultdict(set)
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, callsign: str, socket: WebSocket) -> None:
        await socket.accept()
        self.connections[callsign].add(socket)

    def remove(self, callsign: str, socket: WebSocket) -> None:
        self.connections[callsign].discard(socket)
        if not self.connections[callsign]:
            self.connections.pop(callsign, None)

    async def emit(self, message: dict[str, Any]) -> None:
        users = {message["from"], message["to"]}
        for user in users:
            for socket in tuple(self.connections.get(user, ())):
                try:
                    await socket.send_json({"type": "message.created", "data": message})
                except Exception:
                    self.remove(user, socket)

    def listener(self, value: Message) -> None:
        if self.loop is not None:
            payload = {
                "id": _message_id(value.recipient, value.sequence),
                "from": value.author,
                "to": value.recipient,
                "body": value.body,
                "created_at": _timestamp(value.created_at),
            }
            asyncio.run_coroutine_threadsafe(self.emit(payload), self.loop)


def _timestamp(value: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(value))


def _message_id(recipient: str, sequence: int) -> str:
    return _b64(f"{recipient}:{sequence}".encode())


def _parse_message_id(value: str) -> tuple[str, int]:
    try:
        recipient, sequence = _unb64(value).decode().rsplit(":", 1)
        return recipient, int(sequence)
    except (ValueError, UnicodeDecodeError):
        raise APIError(404, "not_found", "Message not found.") from None


def _message(value: StoredMessage) -> dict[str, Any]:
    return {
        "id": _message_id(value.recipient, value.sequence),
        "from": value.author,
        "to": value.recipient,
        "body": value.body,
        "created_at": _timestamp(value.created_at),
    }


def create_api(
    *,
    accounts: AccountStore,
    messages: MessageStore,
    core: ServerCore,
    secret: str,
    token_lifetime: int = 3600,
    cors_origins: tuple[str, ...] = (),
    hub: EventHub | None = None,
) -> FastAPI:
    app = FastAPI(title="OpenQSP Internet API", version="1.0.0")
    signer, events = Signer(secret, token_lifetime), hub or EventHub()
    bearer = HTTPBearer(auto_error=False)
    app.state.events = events
    core.add_message_listener(events.listener)
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.on_event("startup")
    async def startup() -> None:
        events.loop = asyncio.get_running_loop()

    @app.exception_handler(APIError)
    async def api_error(_: Request, error: APIError) -> JSONResponse:
        content: dict[str, Any] = {
            "error": {"code": error.code, "message": error.message}
        }
        if error.details:
            content["error"]["details"] = error.details
        return JSONResponse(status_code=error.status, content=content)

    @app.exception_handler(RequestValidationError)
    async def validation(_: Request, error: RequestValidationError) -> JSONResponse:
        details = {
            ".".join(str(x) for x in item["loc"]): item["msg"]
            for item in error.errors()
        }
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request.",
                    "details": details,
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        logger.exception("unexpected Internet API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "internal_error", "message": "Internal server error."}
            },
        )

    def user(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer)
        ] = None,
    ) -> str:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise APIError(401, "invalid_token", "Authentication required.")
        return signer.identity(credentials.credentials)

    @app.post("/api/v1/auth/login")
    def login(body: Login) -> dict[str, Any]:
        try:
            callsign = accounts.authenticate(body.callsign, body.password)
        except InvalidCredentialsError:
            raise APIError(
                401, "invalid_credentials", "Invalid callsign or password."
            ) from None
        return {
            "access_token": signer.access(callsign),
            "token_type": "bearer",
            "user": {"callsign": callsign},
        }

    @app.get("/api/v1/me")
    def me(callsign: Annotated[str, Depends(user)]) -> dict[str, str]:
        return {"callsign": callsign}

    @app.post("/api/v1/messages", status_code=201)
    async def send(
        body: Send,
        callsign: Annotated[str, Depends(user)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, Any]:
        try:
            recipient = normalize_callsign(body.to)
        except InvalidFieldError as error:
            raise APIError(
                422, "validation_error", "Invalid request.", {"to": str(error)}
            ) from None
        if idempotency_key is not None and (not 1 <= len(idempotency_key) <= 128):
            raise APIError(
                422,
                "validation_error",
                "Invalid request.",
                {"Idempotency-Key": "Must contain 1 to 128 characters."},
            )
        digest = hashlib.sha256(
            json.dumps({"to": recipient, "body": body.body}, sort_keys=True).encode()
        ).hexdigest()
        try:
            acceptance = core.send_message(
                created_at=int(time.time()),
                author=callsign,
                recipient=recipient,
                body=body.body,
                idempotency_key=idempotency_key,
                request_hash=digest,
            )
        except InvalidFieldError as error:
            code = "message_too_long" if "body" in str(error) else "validation_error"
            raise APIError(
                422, code, "Invalid request.", {"request": str(error)}
            ) from None
        except IdempotencyConflictError:
            raise APIError(
                409, "conflict", "Idempotency key was used for a different request."
            ) from None
        result = _message(acceptance.message)
        return {"message": result}

    @app.get("/api/v1/messages")
    def list_messages(
        callsign: Annotated[str, Depends(user)],
        limit: int = Query(50, ge=1, le=200),
        cursor: str | None = None,
        with_: str | None = Query(None, alias="with"),
    ) -> dict[str, Any]:
        after = 0 if cursor is None else signer.cursor_value(cursor, callsign, "page")
        try:
            peer = None if with_ is None else normalize_callsign(with_)
        except InvalidFieldError:
            raise APIError(
                422,
                "validation_error",
                "Invalid request.",
                {"with": "Invalid callsign."},
            ) from None
        values, more = messages.api_list(
            callsign=callsign, after=after, limit=limit, peer=peer
        )
        next_cursor = (
            signer.cursor(callsign, values[-1].api_sequence, "page")
            if more and values
            else None
        )
        return {"messages": [_message(v) for v in values], "next_cursor": next_cursor}

    @app.get("/api/v1/messages/{message_id}")
    def get_message(
        message_id: str, callsign: Annotated[str, Depends(user)]
    ) -> dict[str, Any]:
        recipient, sequence = _parse_message_id(message_id)
        value = messages.get_message(recipient=recipient, sequence=sequence)
        if value is None or callsign not in (value.author, value.recipient):
            raise APIError(404, "not_found", "Message not found.")
        return {"message": _message(value)}

    @app.get("/api/v1/sync")
    def sync(
        callsign: Annotated[str, Depends(user)], cursor: str | None = None
    ) -> dict[str, Any]:
        after = 0 if cursor is None else signer.cursor_value(cursor, callsign, "sync")
        high = messages.api_high_water()
        if after > high:
            raise APIError(400, "invalid_request", "Invalid cursor.")
        values, _ = messages.api_list(callsign=callsign, after=after, limit=200)
        # Advance only through returned changes; when none, safely capture the global high-water.
        position = values[-1].api_sequence if values else high
        return {
            "messages": [_message(v) for v in values],
            "cursor": signer.cursor(callsign, position, "sync"),
        }

    @app.websocket("/api/v1/ws")
    async def websocket(socket: WebSocket, token: str | None = Query(None)) -> None:
        try:
            if token is None:
                auth = socket.headers.get("authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else ""
            callsign = signer.identity(token)
        except APIError:
            await socket.close(code=4401)
            return
        await events.connect(callsign, socket)
        try:
            while True:
                await socket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            events.remove(callsign, socket)

    return app
