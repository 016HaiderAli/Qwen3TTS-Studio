# Voice Studio (MVP)

A web application for designing custom voices and generating narrated audio with
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS). Users sign in with Google,
create a voice by describing it, listen to and approve a generated preview, then
paste a script (with optional natural-language delivery direction) to produce a
narration they can play back and download.

The application is a frontend/backend split with a **GPU worker** that runs the
Qwen3-TTS inference. In this preview environment the same worker runs in **mock
mode** (synthetic WAVs, no GPU) so the full workflow is demonstrable; swapping in
a real GPU worker requires no web-tier changes.

## Architecture

| Component | Tech | Role |
| --- | --- | --- |
| `frontend/` | React + Vite + TypeScript | Login, voice library, design wizard, narration studio, history, playback/download |
| `backend/` | FastAPI + SQLite (SQLAlchemy) | Auth/sessions, voice & narration CRUD, job queue, audio storage/serving |
| `worker/` | Python (`qwen-tts_worker`) | Polls the internal job API; `mock` backend (default) or real `qwen` backend |

The Vite dev server proxies `/api` and `/auth` to the FastAPI backend on
`localhost:8000`, so the browser talks to a single origin (see
`docs/MVP_ARCHITECTURE.md` and `docs/DEVIATIONS.md`).

```
Browser (Vite :5173) --/api,/auth--> FastAPI (:8000) --internal job API--> GPU/mock worker
                                       |--> SQLite (data/)
                                       |--> local storage (reference.wav, prompt .pt, final wav)
```

## Quick start (preview, no GPU required)

Prerequisites: Python 3.11, Node 20+.

```bash
# Backend dependencies
pip install -r backend/requirements.txt

# Frontend dependencies
npm --prefix frontend install

# Set a worker token (dev value is fine for preview)
export WORKER_TOKEN=dev-worker-token
export DEV_LOGIN=1

# Start backend + mock worker + frontend dev server
./start.sh
```

Then open the exposed preview port (the Vite dev server, default `:5173`). Sign
in with **dev login** (`/auth/dev-login?email=you@example.com`) or configure real
Google OAuth (below).

## Real Google login

1. Create an OAuth 2.0 client in [Google Cloud Console](https://console.cloud.google.com/apis/credentials).
2. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `backend/.env` (see `backend/.env.example`).
3. Register the redirect URI: `FRONTEND_URL + /auth/callback` (e.g. `https://<preview-domain>/auth/callback`).

Until credentials are provided, `GET /auth/login` returns 503 and `DEV_LOGIN=1`
enables the test-only dev login. Never enable `DEV_LOGIN` in production.

## Real GPU worker

On a CUDA host:

```bash
pip install -r worker/requirements.txt -r worker/requirements-qwen.txt
export BACKEND_URL=http://<backend-host>:8000
export WORKER_TOKEN=<shared with backend>
export WORKER_BACKEND=qwen
python -m qwen_tts_worker.main --backend qwen
```

The worker downloads `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign` and
`Qwen/Qwen3-TTS-12Hz-1.7B-Base` (~4.5 GB BF16 each) on first use. See
`worker/.env.example` for all options (device, dtype, model ids, keep-design-loaded).

## Configuration

All configuration is environment-driven; copy `.env.example` files and never
commit `.env`. Key variables:

- Backend: `DATABASE_URL`, `STORAGE_DIR`, `WORKER_TOKEN`, `DEV_LOGIN`,
  `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `FRONTEND_URL`, `COOKIE_SECURE`.
- Worker: `BACKEND_URL`, `WORKER_TOKEN`, `WORKER_BACKEND=mock|qwen`,
  `QWEN_MODEL_DESIGN`, `QWEN_MODEL_BASE`, `QWEN_DEVICE`, `QWEN_DTYPE`.

## Testing

```bash
# Backend: unit + API + mock-worker integration (no GPU)
python -m pytest backend/tests

# Frontend: unit tests + lint + production build + type check
npm --prefix frontend test
npm --prefix frontend run lint
npm --prefix frontend run build
```

## Documentation

- `docs/MVP_ARCHITECTURE.md` — authoritative architecture, scope, and feature traceability.
- `docs/ARCHITECTURE.md` — full design write-up.
- `docs/DEVIATIONS.md` — implementation deviations and design decisions.
- `docs/VERIFICATION_REPORT.md` — what was verified (mock worker) vs. what requires a real GPU.

## Security notes

- Sessions store a SHA-256 hash of the httpOnly cookie token; revocation and expiry are server-side.
- Ownership (`owner_id`) is enforced on every query; worker routes are gated by a bearer token.
- Worker never receives DB/storage/OAuth credentials.
- Storage paths are relative and traversal-checked; audio is served only through authenticated routes.
