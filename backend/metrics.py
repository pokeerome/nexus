import json
import sys
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone

# US dollars per 1 million tokens. These are OpenAI's list prices; update them if they change.
PRICES = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


def cost_usd(model: str, input_tokens: int, output_tokens: int = 0) -> float:
    price = PRICES.get(model)
    if price is None:
        return 0.0
    return (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000


@dataclass
class RequestInfo:
    request_id: str
    started: float = field(default_factory=time.perf_counter)
    user_id: int | None = None
    workspace_id: int | None = None
    steps_ms: dict = field(default_factory=dict)
    counts: dict = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    embed_tokens: int = 0
    cost: float = 0.0
    ai_calls: int = 0
    parent_id: str | None = None


_current: ContextVar[RequestInfo | None] = ContextVar("request_info", default=None)


def start_request():
    """Begin measuring one request (or one background job). Returns (info, token)."""
    info = RequestInfo(request_id=uuid.uuid4().hex[:12])
    return info, _current.set(info)


def end_request(token) -> None:
    _current.reset(token)


def current() -> RequestInfo | None:
    return _current.get()


def add_usage(model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    info = current()
    if info is None:
        return
    if model.startswith("text-embedding"):
        info.embed_tokens += input_tokens
    else:
        info.input_tokens += input_tokens
        info.output_tokens += output_tokens
    info.cost += cost_usd(model, input_tokens, output_tokens)
    info.ai_calls += 1


def add_step(name: str, ms: float) -> None:
    info = current()
    if info is not None:
        info.steps_ms[name] = round(info.steps_ms.get(name, 0) + ms, 1)


@contextmanager
def timed(name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        add_step(name, (time.perf_counter() - started) * 1000)


def mark(name: str) -> None:
    """Record how many milliseconds have passed since the request began."""
    info = current()
    if info is not None and name not in info.steps_ms:
        info.steps_ms[name] = round((time.perf_counter() - info.started) * 1000, 1)


def count(name: str, n: int = 1) -> None:
    info = current()
    if info is not None:
        info.counts[name] = info.counts.get(name, 0) + n


def log_event(event: str, level: str = "info", **fields) -> None:
    """One JSON line per event. Only ids, numbers and names go in here, never user text."""
    info = current()
    line = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level,
        "event": event,
        "request_id": info.request_id if info else None,
        **fields,
    }
    print(json.dumps(line, default=str), file=sys.stdout, flush=True)


def _insert_usage(info: RequestInfo, kind: str, status: int, duration_ms: int) -> None:
    from database import SessionLocal
    from models import UsageEvent

    db = SessionLocal()
    try:
        db.add(
            UsageEvent(
                request_id=info.request_id,
                workspace_id=info.workspace_id,
                user_id=info.user_id,
                kind=kind,
                status=status,
                duration_ms=duration_ms,
                input_tokens=info.input_tokens,
                output_tokens=info.output_tokens,
                embed_tokens=info.embed_tokens,
                cost_usd=info.cost,
                details={
                    "steps_ms": info.steps_ms,
                    "counts": info.counts,
                    "parent_request_id": info.parent_id,
                },
            )
        )
        db.commit()
    finally:
        db.close()


def finish(info: RequestInfo, kind: str, status: int, extra_log: dict | None = None) -> None:
    """Log the request, and save a usage row when it used AI (or is a question)."""
    duration_ms = int((time.perf_counter() - info.started) * 1000)
    fields = {
        "kind": kind,
        "status": status,
        "duration_ms": duration_ms,
        "user_id": info.user_id,
        "workspace_id": info.workspace_id,
        **(extra_log or {}),
    }
    if info.parent_id:
        fields["parent_request_id"] = info.parent_id
    if info.ai_calls:
        fields.update(
            ai_calls=info.ai_calls,
            input_tokens=info.input_tokens,
            output_tokens=info.output_tokens,
            embed_tokens=info.embed_tokens,
            cost_usd=round(info.cost, 6),
        )
    if info.steps_ms:
        fields["steps_ms"] = info.steps_ms
    if info.counts:
        fields["counts"] = info.counts
    log_event("request_finished", level="error" if status >= 500 else "info", **fields)

    if info.ai_calls or kind in ("chat", "agent"):
        try:
            _insert_usage(info, kind, status, duration_ms)
        except Exception as e:  # saving numbers must never break a request
            log_event("usage_save_failed", level="error", error=type(e).__name__)


ROUTE_KINDS = {"chat": "chat", "agent_chat": "agent", "search": "search", "upload_document": "upload"}


class RequestLogMiddleware:
    """Gives every request an id (also sent back as X-Request-ID) and logs how it went."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        info, token = start_request()
        status = 500
        for name, value in scope.get("headers", []):
            if name == b"x-parent-request-id":
                info.parent_id = value.decode("latin-1")[:32]

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", info.request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            try:
                path = scope.get("path", "")
                if path != "/health":
                    route = scope.get("route")
                    if path.startswith("/mcp"):
                        kind, shown = "tool", "/mcp"
                    else:
                        kind = ROUTE_KINDS.get(getattr(route, "name", ""), "other")
                        shown = getattr(route, "path", path)
                    workspace = scope.get("path_params", {}).get("workspace_id")
                    if workspace is not None and info.workspace_id is None:
                        info.workspace_id = int(workspace)
                    finish(
                        info, kind, status,
                        {"method": scope.get("method"), "path": shown},
                    )
            except Exception as e:
                print(f"observability error: {e!r}", flush=True)
            end_request(token)