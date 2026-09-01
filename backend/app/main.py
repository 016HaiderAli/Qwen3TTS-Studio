"""FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import init_db
from .routers import auth, builtin_voices, files, internal, jobs, maintenance, narrations, voice_clone, voice_previews, voices
from .voice import ensure_builtin_voice

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Voice Studio MVP - Qwen3-TTS voice design and narration web app.",
)

# CORS: the frontend dev server (Vite on :5173) is always allowed so public
# endpoints like voice previews work even when fetched by absolute URL;
# same-origin traffic keeps working via the Vite proxy in dev and the shared
# origin in production. Extra origins can be added via CORS_ORIGINS.
_allowed_origins: list[str] = []
for _origin in (settings.frontend_url, *settings.origin_list):
    _trimmed = _origin.rstrip("/")
    if _trimmed and _trimmed not in _allowed_origins:
        _allowed_origins.append(_trimmed)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
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
    ensure_builtin_voice()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}


app.include_router(auth.router)
# voice_clone.router first: its literal POST /api/voices/clone must be
# preferred over voices.router's dynamic /{voice_id} subresource routes.
app.include_router(voice_clone.router, prefix="/api/voices", tags=["voice-clone"])
app.include_router(voices.router)
app.include_router(builtin_voices.router)
app.include_router(narrations.router)
app.include_router(jobs.router)
app.include_router(files.router)
app.include_router(files.audio_export_router)
app.include_router(voice_previews.router)
app.include_router(internal.router)
app.include_router(maintenance.router)
