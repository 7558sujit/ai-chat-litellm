import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from . import db, llm

logging.basicConfig(level=logging.INFO)
DEFAULT_SYSTEM_PROMPT = os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant.")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="AI Chat", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str
    message: str
    system_prompt: str | None = None

    @field_validator("session_id")
    @classmethod
    def _sid(cls, v: str) -> str:
        if not 1 <= len(v) <= 128:
            raise ValueError("session_id must be 1-128 characters")
        return v

    @field_validator("message")
    @classmethod
    def _msg(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 4000:
            raise ValueError("message must be 1-4000 characters after trimming")
        return v


@app.exception_handler(RequestValidationError)
async def _validation(_: Request, exc: RequestValidationError):
    errs = [{"loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errs})


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception):
    logging.getLogger("app").exception("unhandled")
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health():
    db.ping()
    return {"status": "ok", "keys_configured": len(llm.get_keys()), "cache_enabled": llm.litellm.cache is not None}


@app.post("/chat")
async def chat(req: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    if req.system_prompt and req.system_prompt.strip():
        db.set_system_prompt(req.session_id, req.system_prompt.strip())
    system = db.get_system_prompt(req.session_id) or DEFAULT_SYSTEM_PROMPT
    past = [{"role": m["role"], "content": m["content"]} for m in db.history(req.session_id)]
    messages = [{"role": "system", "content": system}, *past, {"role": "user", "content": req.message}]
    try:
        reply, meta = await llm.complete(messages, llm.parse_simulation(x_simulate_failure))
    except llm.AllProvidersUnavailable:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})
    db.save_turn(req.session_id, req.message, reply, meta)
    return {"session_id": req.session_id, "reply": reply, "metadata": meta}


@app.get("/sessions/{session_id}/messages")
def session_messages(session_id: str):
    msgs = db.history(session_id)
    if not msgs:
        return JSONResponse(status_code=404, content={"detail": "session not found"})
    return {"session_id": session_id, "messages": msgs}
