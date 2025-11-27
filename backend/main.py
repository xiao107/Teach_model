import os
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent


load_dotenv()

API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

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


sessions: Dict[str, agent.ConversationManager] = {}


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    manager = sessions.get(request.session_id)
    if manager is None:
        manager = agent.ConversationManager()
        sessions[request.session_id] = manager

    reply = await agent.process_user_command(
        request.message, manager, API_KEY, model_name=MODEL_NAME
    )
    return ChatResponse(session_id=request.session_id, reply=reply)


# Serve frontend files located one level up in the frontend/ directory.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
