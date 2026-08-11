# Verification Report

Date: 2026-08-11

This report records exactly what was verified for the Voice Studio MVP and what
still requires a real GPU host. It follows the test/verification plan in
`docs/MVP_ARCHITECTURE.md` §3.8 and separates every claim by provenance.

## Provenance categories

- **(A) Notebook-proven** — behavior taken directly from
  `reference/Voice_Studio.ipynb` (cells cited) and/or the pinned `qwen-tts==0.1.1`
  source; trustworthy as the model API contract.
- **(B) Verified here (CPU / mock worker)** — executed and passed in this
  environment's test suites, lint, type check, production build, and a live
  uvicorn + mock-worker + Vite run.
- **(C) Implemented, not GPU-validated** — code written to the (A) contract but
  not executable here (no CUDA, no torch, no qwen-tts). Requires a CUDA host.
- **(D) Not supported by `qwen-tts==0.1.1`** — requested feature that the pinned
  API does not provide; handled as a documented limitation.

## Environment

- CPU-only sandbox: no CUDA GPU, no `torch`, no `qwen-tts` installed.
- Python 3.11, Node 22, SQLite, local filesystem storage.
- A single exposed port; the Vite dev server proxies `/api` and `/auth` to FastAPI.

## What is (A) notebook-proven / (D) unsupported

- `create_voice_clone_prompt(ref_audio=str(path), ref_text=...)` — filesystem-path
  form (notebook cell 21). The worker passes a decoded temp-WAV path, not a numpy
  tuple (DEVIATIONS §7).
- Prompt persistence schema (notebook cells 25/27): `icl_mode`, `ref_code (108,16)`,
  `ref_spk_embedding (2048,)`, `ref_text: str`, `x_vector_only_mode`; `torch.save` /
  `torch.load(weights_only=True)`; restored as `VoiceClonePromptItem` (cell 29).
- `generate_voice_design(text, language, instruct)` (cell 15) and
  `generate_voice_clone(text, language, voice_clone_prompt=...)` under
  `torch.inference_mode()` (cell 32/36), returning `(wavs, sample_rate)`.
- **(D)** `generate_voice_clone` has **no `instruct` parameter** in `qwen-tts==0.1.1`
  (verified in the packaged source). Delivery direction therefore shapes the
  reference voice at design time and otherwise uses the Base model's native
  punctuation/paragraph path; it is never forwarded to the narration call
  (DEVIATIONS §1).
- Version evidence: notebook cell 7 installed `qwen-tts 0.1.1`, which pins
  `transformers==4.57.3` and `accelerate==1.12.0`; cell 9 reports PyTorch
  `2.11.0+cu128`, Python 3.12, NVIDIA **Tesla T4**, `flash-attn` absent. These are
  documented in `worker/requirements-qwen.txt`.

## Validated here — (B) backend test suite

`python -m pytest backend/tests` — **84 tests passed**. Coverage:

- **Chunking** (`test_chunking.py`): notebook port — paragraph/sentence splitting,
  greedy 80-word packing, >80-word scripts, empty-script rejection, and the
  documented deviation: paragraph breaks preserved inside a chunk (`\n\n`).
- **Audio** (`test_audio.py`): WAV parse/validate, size limits, concatenation,
  sample-rate mismatch rejection, empty-input rejection.
- **Security** (`test_security.py`): opaque tokens, SHA-256 hash-at-rest, PKCE S256.
- **Auth** (`test_auth.py`): dev-login, `/api/me`, logout invalidation, Google OAuth
  callback (mocked transport) creating a user + session, state-mismatch rejection,
  503 when Google is unconfigured, PKCE params in the auth URL.
- **Voices** (`test_voices.py`): CRUD, unsupported-language rejection, design job
  enqueue, approval guard, per-user isolation (404), delete.
- **Narrations** (`test_narrations.py`): approved-voice requirement (409), chunking
  stored + delivery direction persisted into the worker payload, history with voice
  name, per-user isolation, empty-script rejection.
- **Internal job API** (`test_jobs_internal.py`): worker-token auth (401 without /
  with wrong token), design lifecycle (claim → invalid WAV 422 → valid WAV upload →
  complete → `preview_ready` + streamable reference), fail→retry→failed with
  `voice` returning to `draft`, completing a non-running job → 409, chunk-field
  validation, and **sample-rate authority**: when a worker reports a rate that
  contradicts the uploaded WAV artifacts, the stored narration rate is parsed from
  the WAV (authoritative) and the mismatch is logged.
- **Worker client** (`test_worker_client.py`): poll/204, poll claim, upload
  multipart shape, complete/fail bodies, error propagation.
- **Prompt schema** (`test_prompt_schema.py`): cell-25 dict contract with strict
  shape/type validation (`ref_code` exactly `(108,16)`, `ref_spk_embedding` exactly
  `(2048,)`, bool flags, `ref_text` str when ICL mode), version-constant evidence,
  lenient mode for future versions, lazy torch import (ImportError when torch is
  absent).
- **GPU startup checks** (`test_startup_checks.py`): every `checks.py` diagnostic —
  missing torch, CUDA unavailable, bad/missing device index, missing/wrong
  `qwen-tts` version, incomplete API surface, invalid/non-float dtype, and an
  all-green `run_startup_checks` + `require_ok`.
- **Mock-worker E2E** (`test_mock_worker_e2e.py`): full flow via the internal HTTP
  contract — login → create voice → design → preview_ready → approve → approved →
  narrate (single- and multi-chunk, with delivery direction, with paragraph breaks)
  → ready narration with sample rate + duration + downloadable WAV; per-chunk
  progress reported through the user-facing job endpoint.

## Validated here — (B) frontend

- `npm --prefix frontend test` (9 passed): API client behavior (success, 401 →
  ApiError, error-detail surfacing, 204, same-origin credentials); login page
  (redirect to Google authorization URL, graceful error when Google is
  unconfigured); status badge labels.
- `npm --prefix frontend run lint`, `tsc --noEmit` type check, and production
  `vite build` all clean.

## Validated here — (B) live integration (real uvicorn + mock worker over HTTP)

A live run against `uvicorn` on `:8000` with the mock worker and the Vite dev
server on `:5173`:

1. `POST /auth/dev-login` → session cookie works with `/api/me`.
2. `POST /api/voices` → `draft`; `POST /api/voices/{id}/design` → worker processed
   the `design` job → `preview_ready`; reference WAV downloaded (RIFF, valid).
3. `POST /api/voices/{id}/approve` → worker processed `clone_prompt` (90-byte mock
   prompt) → `approved`.
4. `POST /api/narrations` (multi-paragraph script + delivery direction) → worker
   processed `narration` → `ready`; final WAV downloaded (RIFF) with recorded
   `duration_sec` and `sample_rate=24000`.
5. Worker auth: `POST /internal/jobs/poll` without/with a wrong token → 401.
6. Vite proxy: `http://localhost:5173/api/health` → `{"status":"ok"}`, and the
   preview host header (`.monkeycode-ai.live`) is accepted by `allowedHosts`.
   Preview URL: https://5173-56e3366d35ac4142.monkeycode-ai.live

## Security / authorization review

- Session tokens stored as SHA-256 hashes; cookie is httpOnly, SameSite=Lax,
  `Secure` behind `COOKIE_SECURE=1`; server-side expiry + logout revocation.
- Google OAuth uses Authorization Code + PKCE (S256) with `state` validation;
  token/userinfo exchange goes through injectable httpx transport (tested).
- Every `/api/*` query is scoped by `owner_id`; cross-user access returns 404
  (tested for voices, narrations, files, jobs).
- Worker internal routes require a bearer token matched with a constant-time
  compare; routes return 404 entirely when `WORKER_TOKEN` is unset.
- Storage paths are relative to the storage root and traversal-checked
  (`safe_resolve`); uploads are size-limited and WAV-validated.
- No secrets committed: `.env`/`data/`/`storage/`/`*.wav`/`*.pt`/`node_modules`/
  `dist` are git-ignored; only `.env.example` files are committed.
- The web tier never receives worker credentials, and the worker never receives
  DB/storage/OAuth credentials (byte-passing boundary).

## (C) Implemented, NOT validated here — requires a real GPU host

The **real Qwen3-TTS backend** (`worker/qwen_tts_worker/qwen_backend.py` and the
startup checks in `checks.py`) is written to mirror the (A) notebook contract but
could not be executed in this CPU-only environment. The following are therefore
**unvalidated** until the GPU acceptance run:

- Model downloads (`Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`, `-Base`) and exact
  `from_pretrained(device_map, dtype)` behavior under `qwen-tts 0.1.1` with
  PyTorch 2.11+ / bfloat16 on a Tesla T4.
- `generate_voice_design(text, language, instruct)` output on real models.
- Temp-file path form of `create_voice_clone_prompt` → cell-25 dict → `torch.save`
  → `torch.load(weights_only=True)` round-trip → `VoiceClonePromptItem` → per-chunk
  `generate_voice_clone` under `torch.inference_mode()`.
- GPU VRAM behavior of the one-model-at-a-time lifecycle (design released after
  use, base kept resident). **No VRAM budget (e.g. "fits on a 16 GB T4") is
  claimed** — it is verified only by this acceptance run.
- The startup checks on a real CUDA host (their failure paths are unit-tested here;
  their CUDA-specific branches run only on real hardware).
- End-to-end delivery direction effect on real narration (design-time `instruct` +
  native prosody path).

### Recommended GPU acceptance steps (on the user's GPU host/Colab)
1. Install `worker/requirements.txt` + `worker/requirements-qwen.txt`
   (`qwen-tts==0.1.1`, `transformers==4.57.3`, `accelerate==1.12.0`; CUDA-enabled
   torch matching the host).
2. Run the notebook cells 1–28 of `reference/Voice_Studio.ipynb` to confirm the
   environment matches the notebook (T4, PyTorch 2.11+, bfloat16).
3. Start the backend with a real `WORKER_TOKEN`, then run
   `cd worker && python -m qwen_tts_worker.main --backend qwen`; confirm the
   startup checks pass.
4. Re-run the live E2E flow and confirm real WAV output (compare against the
   notebook's golden outputs).
5. If any `qwen-tts` API detail differs, adjust `worker/qwen_tts_worker/qwen_backend.py`
   only (the web tier is already correct) and update `docs/DEVIATIONS.md`.

## Known scope notes

- Google real login requires user-supplied OAuth credentials (documented in
  `docs/DEVIATIONS.md` §3).
- Narration delivery direction is applied at design time (`instruct` on
  `generate_voice_design`) plus native punctuation/paragraph preservation on
  narration; `qwen-tts==0.1.1` has no per-utterance `instruct` parameter (D) — see
  `docs/DEVIATIONS.md` §1; the UI does not claim unsupported per-utterance
  instruction injection.
- `docs/MVP_ARCHITECTURE.md` §3.3 specifies `POST /internal/jobs/{id}/chunks`;
  the implementation uses a single generic
  `POST /internal/jobs/{id}/artifact` with a `field` parameter
  (`reference_audio`, `prompt_pt`, `chunk_<i>`) to keep one upload path for all
  artifact kinds — see `docs/DEVIATIONS.md` §6.
