"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .routers import auth, builtin_voices, files, internal, jobs, narrations, voices

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Voice Studio MVP - Qwen3-TTS voice design and narration web app.",
)

if settings.origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # pragma: no cover
    if settings.debug:
        raise exc
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


app.include_router(auth.router)
app.include_router(voices.router)
app.include_router(builtin_voices.router)
app.include_router(narrations.router)
app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(internal.router)
