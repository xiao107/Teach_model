"""
FastAPI application: routes, middleware, uploads, session APIs, SSE, export.

Implements TASK-201 (title), TASK-202 (export), TASK-205 (request_id,
rate limit, circuit breaker), plus config-driven settings (TASK-204).
"""
import asyncio
import html as html_mod
import io
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent
from .config import settings
from .sessions import SessionStore

load_dotenv()


def setup_logging() -> logging.Logger:
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logging.basicConfig(level=settings.log_level.upper(), handlers=[stream_handler, file_handler], force=True)
    logger = logging.getLogger("teach_model")
    logger.info("Logging initialized. Level=%s, file=%s", settings.log_level, log_file)
    return logger


logger = setup_logging()


# ---------------------------------------------------------------- TASK-205: request_id middleware

class RequestContextMiddleware:
    """Inject a request_id into every request and response, and into logs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = scope.get("headers")
        rid = uuid.uuid4().hex[:12]
        scope["state"] = {"request_id": rid}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                headers.append((b"x-request-id", rid.encode()))
                if message["status"] >= 400:
                    logger.warning("HTTP %s request_id=%s path=%s", message["status"], rid, scope.get("path"))
            await send(message)

        await self.app(scope, receive, send_wrapper)


# ---------------------------------------------------------------- TASK-205: rate limit + circuit breaker

class RateLimiter:
    """Sliding-window per-IP limiter for chat/stream endpoints."""

    def __init__(self, max_per_minute: int) -> None:
        self.max = max_per_minute
        self._hits: Dict[str, deque] = defaultdict(deque)

    def check(self, ip: str) -> bool:
        now = time.time()
        q = self._hits[ip]
        while q and q[0] < now - 60:
            q.popleft()
        if len(q) >= self.max:
            return False
        q.append(now)
        return True


class LLMCircuitBreaker:
    """Open after N consecutive LLM failures; stays open for a cooldown."""

    def __init__(self, failure_threshold: int, cooldown_s: int) -> None:
        self.threshold = failure_threshold
        self.cooldown = cooldown_s
        self._consecutive = 0
        self._opened_at: float = 0.0

    @property
    def is_open(self) -> bool:
        if self._consecutive < self.threshold:
            return False
        return (time.time() - self._opened_at) < self.cooldown

    def record_success(self) -> None:
        self._consecutive = 0

    def record_failure(self) -> None:
        self._consecutive += 1
        if self._consecutive >= self.threshold:
            self._opened_at = time.time()
            logger.warning("LLM circuit breaker OPENED after %d failures", self._consecutive)


rate_limiter = RateLimiter(settings.rate_limit_per_minute)
llm_breaker = LLMCircuitBreaker(settings.breaker_failure_threshold, settings.breaker_cooldown_s)


def error_response(error_code: str, message: str, request: Optional[Request] = None, status_code: int = 500):
    rid = getattr(getattr(request, "state", None), "request_id", "") or uuid.uuid4().hex[:12]
    return JSONResponse(status_code=status_code, content={"error_code": error_code, "message": message, "request_id": rid})


def _rate_limited(http_request: Request) -> Optional[JSONResponse]:
    """Per-IP limit shared by the expensive endpoints (chat / stream / upload).

    限流器此前只被实例化、没有任何接口调用它（形同虚设）。这里统一接入。
    """
    ip = http_request.client.host if http_request.client else "unknown"
    if rate_limiter.check(ip):
        return None
    logger.warning("Rate limit exceeded ip=%s limit=%d/min", ip, settings.rate_limit_per_minute)
    response = error_response(
        "RATE_LIMITED",
        f"请求过于频繁：每分钟最多 {settings.rate_limit_per_minute} 次，请稍后再试。",
        http_request,
        status_code=429,
    )
    response.headers["Retry-After"] = "60"
    return response


# ---------------------------------------------------------------- app setup

session_store = SessionStore(
    db_path=str(Path(__file__).resolve().parent / "sessions.db"),
    idle_ttl_seconds=settings.session_idle_ttl_s,
)


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(settings.session_cleanup_interval_s)
        try:
            session_store.cleanup_idle()
        except Exception:
            logger.exception("Session cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="DeepSeek Data Assistant", lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Uploaded CSV cache: upload_id -> (df, filename, created_at)
upload_store: Dict[str, Tuple[pd.DataFrame, str, float]] = {}


def _purge_uploads() -> None:
    cutoff = time.time() - settings.upload_cache_ttl_s
    stale = [k for k, (_, _, ts) in upload_store.items() if ts < cutoff]
    for k in stale:
        upload_store.pop(k, None)


# ---------------------------------------------------------------- models

class ChatRequest(BaseModel):
    session_id: str
    message: str
    uploaded_file_id: Optional[str] = None  # TASK-106/P1-8: reference by id
    uploaded_file_data: Optional[str] = None  # legacy: full CSV string
    student_level: Optional[str] = "intermediate"
    level_prompt: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    chart: Optional[Dict[str, Any]] = None
    steps: Optional[list] = None
    results: Optional[list] = None  # P0-3: per-action result entries for the frontend


# ---------------------------------------------------------------- helpers

def _load_uploaded_into_session(request: ChatRequest, session_id: str) -> Optional[str]:
    """Put uploaded CSV (by id or legacy inline string) into the session. Returns error text or None."""
    manager = session_store.get(session_id)
    try:
        if request.uploaded_file_id:
            _purge_uploads()
            entry = upload_store.get(request.uploaded_file_id)
            if entry is None:
                return "上传文件已过期（缓存 1 小时），请重新上传。"
            df, filename, _ = entry
            manager.set_uploaded_data(df.copy(), filename)
            logger.info("Uploaded CSV loaded by id shape=%s", df.shape)
            return None
        if request.uploaded_file_data:
            df = pd.read_csv(io.StringIO(request.uploaded_file_data))
            manager.set_uploaded_data(df, "uploaded_file.csv")
            logger.info("Legacy inline CSV loaded shape=%s", df.shape)
            return None
    except Exception as exc:
        logger.exception("Failed to load uploaded CSV")
        return f"上传文件处理失败：{exc}"
    return None


def _get_manager_or_404(session_id: str):
    exists = any(s["session_id"] == session_id for s in session_store.list_sessions())
    if not exists:
        raise HTTPException(status_code=404, detail="Session not found")
    return session_store.get(session_id)


# ---------------------------------------------------------------- chat endpoints

@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest, http_request: Request):
    logger.info("Chat request session=%s message_len=%d", request.session_id, len(request.message))
    limited = _rate_limited(http_request)
    if limited is not None:
        return limited
    if llm_breaker.is_open:
        return error_response("LLM_UNAVAILABLE", "AI 服务暂时不可用（连续失败熔断中），请稍后再试。", status_code=503)

    err = _load_uploaded_into_session(request, request.session_id)
    if err:
        return ChatResponse(session_id=request.session_id, reply=err)

    manager = session_store.get(request.session_id)
    result = await agent.process_user_command(
        request.message, manager, settings.deepseek_api_key,
        model_name=settings.deepseek_model,
        student_level=request.student_level,
        level_prompt=request.level_prompt,
    )
    session_store.save(manager)
    llm_breaker.record_success()
    return ChatResponse(
        session_id=request.session_id,
        reply=result.get("reply", ""),
        chart=result.get("chart"),
        steps=result.get("steps") or [],
        results=result.get("results") or [],
    )


@app.post("/api/chat/stream")
async def chat_stream_endpoint(request: ChatRequest, http_request: Request):
    """SSE streaming chat: status -> delta* -> final."""
    limited = _rate_limited(http_request)
    if limited is not None:
        return limited
    if llm_breaker.is_open:
        return error_response("LLM_UNAVAILABLE", "AI 服务暂时不可用（连续失败熔断中），请稍后再试。", status_code=503)

    session_id = request.session_id
    err = _load_uploaded_into_session(request, session_id)
    if err:
        return error_response("UPLOAD_ERROR", err, status_code=400)

    manager = session_store.get(session_id)

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_delta(event: str, text: str) -> None:
            await queue.put((event, text))

        async def run() -> None:
            try:
                result = await agent.process_user_command(
                    request.message, manager, settings.deepseek_api_key,
                    model_name=settings.deepseek_model,
                    student_level=request.student_level,
                    level_prompt=request.level_prompt,
                    on_delta=on_delta,
                )
                session_store.save(manager)
                llm_breaker.record_success()
                await queue.put(("final", json.dumps({
                    "session_id": session_id,
                    "reply": result.get("reply", ""),
                    "chart": result.get("chart"),
                    "steps": result.get("steps") or [],
                    "results": result.get("results") or [],
                }, ensure_ascii=False)))
            except Exception as exc:
                llm_breaker.record_failure()
                request_id = getattr(getattr(http_request, "state", None), "request_id", "")
                logger.exception("Stream processing failed request_id=%s", request_id)
                await queue.put(("error", json.dumps({
                    "message": str(exc),
                    "request_id": request_id,
                }, ensure_ascii=False)))
            finally:
                await queue.put(("done", ""))

        runner = asyncio.create_task(run())
        try:
            yield f"event: status\ndata: {json.dumps({'message': '正在思考...'}, ensure_ascii=False)}\n\n"
            while True:
                event, text = await queue.get()
                if event == "done":
                    break
                if event == "status":
                    yield f"event: status\ndata: {json.dumps({'message': text}, ensure_ascii=False)}\n\n"
                elif event in ("final", "error", "result"):
                    # result payloads are pre-encoded JSON by the agent layer
                    yield f"event: {event}\ndata: {text}\n\n"
                else:
                    yield f"event: {event}\ndata: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
        finally:
            runner.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------- upload

@app.post("/api/upload")
async def upload_csv(http_request: Request, file: UploadFile = File(...)):
    logger.info("Upload request filename=%s", file.filename)
    limited = _rate_limited(http_request)
    if limited is not None:
        return limited
    if not file.filename or not file.filename.lower().endswith(".csv"):
        return error_response("UNSUPPORTED_TYPE", "仅支持 CSV 文件", status_code=400)

    content = await file.read()
    if len(content) > settings.upload_max_bytes:
        return error_response("FILE_TOO_LARGE", f"文件超过大小上限（{settings.upload_max_bytes // 1024 // 1024}MB）", status_code=413)

    try:
        df = pd.read_csv(io.StringIO(content.decode("utf-8")))
        if df.empty:
            return error_response("EMPTY_FILE", "CSV 文件为空", status_code=400)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to parse CSV")
        return error_response("PARSE_ERROR", f"CSV 解析失败：{exc}", status_code=400)

    upload_id = uuid.uuid4().hex[:16]
    upload_store[upload_id] = (df, file.filename, time.time())
    logger.info("CSV cached upload_id=%s shape=%s", upload_id, df.shape)
    return {"success": True, "upload_id": upload_id, "filename": file.filename, "shape": list(df.shape)}


# ---------------------------------------------------------------- session APIs

@app.get("/api/sessions")
async def list_sessions():
    return {"sessions": session_store.list_sessions()}


@app.get("/api/sessions/{session_id}")
async def session_detail(session_id: str):
    manager = _get_manager_or_404(session_id)
    snap = manager.snapshot()
    return {
        "session_id": session_id,
        "title": snap.get("title", ""),
        "history": snap.get("history", []),
        "dataset_name": snap.get("dataset_name"),
    }


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True}


@app.post("/api/sessions/{session_id}/generate-title")
async def generate_title(session_id: str):
    """TASK-201: LLM-generated short title for the session."""
    manager = _get_manager_or_404(session_id)
    history = manager.get_history()
    first_user = next((m["content"] for m in history if m["role"] == "user"), "")
    first_assistant = next((m["content"] for m in history if m["role"] == "assistant"), "")
    if not first_user:
        return error_response("EMPTY_SESSION", "会话还没有对话内容，无法生成标题", status_code=400)

    title = await agent.generate_session_title(
        first_user, first_assistant, settings.deepseek_api_key, settings.deepseek_model
    )
    manager.title = title
    session_store.save(manager)
    return {"session_id": session_id, "title": title}


# ---------------------------------------------------------------- export (TASK-202)

_EXPORT_CSS = """
body{font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;max-width:860px;margin:32px auto;padding:0 20px;color:#1D2129;line-height:1.7}
h1.doc-title{font-size:22px;border-bottom:2px solid #4F7CFF;padding-bottom:10px}
.meta{color:#86909C;font-size:13px;margin-bottom:24px}
.msg{margin:16px 0;padding:12px 16px;border-radius:12px}
.msg.user{background:#EAF0FF}
.msg.assistant{background:#fff;border:1px solid #E5E6EB}
.role{font-size:12px;color:#86909C;margin-bottom:6px}
pre{background:#0D1117;color:#E6EDF3;padding:12px;border-radius:8px;overflow-x:auto;font-size:13px}
code{font-family:'SF Mono',Menlo,Consolas,monospace}
table{border-collapse:collapse;margin:8px 0;font-size:13px}
th,td{border:1px solid #E5E6EB;padding:6px 10px}
th{background:#F8F9FB}
.step{font-size:12px;color:#4F7CFF;margin-top:4px}
@media print{body{margin:0}}
"""


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, format: str = "html"):
    """TASK-202: export full conversation as a styled, print-friendly HTML file."""
    if format != "html":
        return error_response("UNSUPPORTED_FORMAT", "当前仅支持 format=html", status_code=400)
    manager = _get_manager_or_404(session_id)
    snap = manager.snapshot()
    history = snap.get("history", [])
    title = snap.get("title") or session_id

    parts = [
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>",
        f"<title>{html_mod.escape(title)}</title>",
        f"<style>{_EXPORT_CSS}</style></head><body>",
        f"<h1 class='doc-title'>{html_mod.escape(title)}</h1>",
        f"<p class='meta'>Teach_model 智能教学平台对话导出 · 共 {len(history)} 条消息</p>",
    ]
    for m in history:
        role = "老师" if m["role"] == "user" else "AI 学生"
        body = html_mod.escape(m["content"])
        # minimal markdown-ish rendering: code fences + line breaks + bold
        body = body.replace("&amp;", "&amp;")
        import re as _re
        body = _re.sub(r"```(\w*)\n(.*?)```", lambda mo: f"<pre><code>{mo.group(2)}</code></pre>", body, flags=_re.DOTALL)
        body = body.replace("\n", "<br/>")
        parts.append(
            f"<div class='msg {m['role']}'><div class='role'>{role}</div><div class='content'>{body}</div></div>"
        )
    parts.append("</body></html>")
    html_text = "".join(parts)

    stamp = time.strftime("%Y%m%d-%H%M")
    safe_title = "".join(c for c in title if c.isalnum() or c in "_-（）() ")[:40].strip() or session_id
    filename = f"{stamp}_{safe_title}.html"
    return StreamingResponse(
        iter([html_text]),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename.encode('utf-8').hex()}"},
    )


# ---------------------------------------------------------------- static frontend

project_root = Path(__file__).resolve().parent.parent
frontend_source = project_root / "frontend"
if frontend_source.exists():
    app.mount("/", StaticFiles(directory=str(frontend_source), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
