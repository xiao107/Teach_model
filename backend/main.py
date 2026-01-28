import os
import logging
from pathlib import Path
from typing import Any, Dict, Optional
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent


load_dotenv()

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def setup_logging() -> logging.Logger:
    """Configure application-wide logging."""
    log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "app.log"

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    logging.basicConfig(level=LOG_LEVEL, handlers=[stream_handler, file_handler], force=True)
    logger = logging.getLogger("tech_llm")
    logger.info("Logging initialized. Level=%s, file=%s", LOG_LEVEL, log_file)
    return logger


logger = setup_logging()

app = FastAPI(title="DeepSeek Data Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    chart: Optional[Dict[str, Any]] = None


sessions: Dict[str, agent.ConversationManager] = {}


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    logger.info("Incoming chat request session=%s message_len=%d", request.session_id, len(request.message))
    manager = sessions.get(request.session_id)
    if manager is None:
        manager = agent.ConversationManager()
        sessions[request.session_id] = manager
        logger.info("New session created session_id=%s", request.session_id)

    result = await agent.process_user_command(
        request.message, manager, API_KEY, model_name=MODEL_NAME
    )
    reply_text = result.get("reply", "")
    chart_payload = result.get("chart")
    logger.info(
        "Reply prepared session=%s reply_len=%d chart=%s",
        request.session_id,
        len(reply_text),
        bool(chart_payload),
    )
    return ChatResponse(session_id=request.session_id, reply=reply_text, chart=chart_payload)


# Serve the frontend directly from the local frontend directory.
project_root = Path(__file__).resolve().parent.parent
frontend_source = project_root / "frontend"
if frontend_source.exists():
    app.mount("/", StaticFiles(directory=str(frontend_source), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
