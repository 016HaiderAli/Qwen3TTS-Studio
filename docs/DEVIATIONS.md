# Implementation Deviations & Design Decisions

This document records deviations from `docs/MVP_ARCHITECTURE.md` discovered during
implementation, plus design decisions forced by the verified Qwen3-TTS API. Each entry
states the reason discovered from primary sources.

## 1. Delivery / Voice Direction on the narration (clone) path

**Requirement (task brief):** a "Delivery / Voice Direction" natural-language input that
tells the selected voice how to perform the script, preferring Qwen3-TTS's native
instruction/control capabilities.

**Verified fact (primary sources):**
- Official Qwen3-TTS README and the `Qwen3-TTS-12Hz-1.7B-Base` model card table:
  `Instruction Control` is **blank** for the Base model (present only for VoiceDesign and
  CustomVoice).
- `qwen_tts/inference/qwen3_tts_model.py` (GitHub `main`, packaged as `qwen-tts 0.1.1`):
  `generate_voice_clone(text, language, ref_audio, ref_text, x_vector_only_mode,
  voice_clone_prompt, non_streaming_mode, **kwargs)` has **no `instruct` parameter**.
  `generate_voice_design(text, instruct, language, ...)` **does** accept `instruct`.

**Consequence:** a natural-language instruction cannot be passed to `generate_voice_clone`
on the current public API without raising `TypeError`.

**Resolution (no unsupported functionality is invented):**
- The **Delivery / Voice Direction** input is a first-class, persisted field on every
  narration and is transported to the GPU worker in the job payload as `instruct`.
- **Voice design** applies it natively: the design `instruct` given to
  `generate_voice_design` is composed from the user's voice description plus the delivery
  direction, so the resulting reference voice embodies the requested delivery. This is the
  demonstrated instruction-control capability.
- **Narration generation** does **not** pass `instruct` to `generate_voice_clone`: the
  `qwen-tts==0.1.1` signature has no such parameter, and forwarding it through `**kwargs`
  would reach `transformers.generate` and raise `TypeError`. The worker logs the direction
  and preserves punctuation and paragraph structure verbatim when passing each chunk to
  `generate_voice_clone`. This is the Base model's documented native expressive path
  ("adaptive control of tone, speaking rate, and emotional expression based on ... text
  semantics"; robust handling of punctuation/pauses). Paragraph boundaries are preserved
  inside chunks with blank-line separators (notebook cells 46/55 flatten them; see
  deviation 2). The earlier capability probe (which would have forwarded `instruct` from a
  hypothetical future API) was removed: the dependency is pinned to `qwen-tts==0.1.1`, and
  startup checks fail fast on any other version rather than silently diverging.
- The `instruct` field is retained in the narration data model, job payload, worker
  interface, and UI so a future `qwen-tts` release that exposes per-utterance instruction
  injection can be wired up without web-tier changes.
- The mock worker consumes and records the delivery direction, proving the end-to-end
  plumbing that the real worker will use.
- The UI labels the field truthfully ("Delivery / Voice Direction") and states that
  per-utterance instruction injection depends on Qwen3-TTS Base API support.

## 2. Chunking preserves paragraph structure inside a chunk

**Architecture doc / notebook:** notebook cells 46/55 split text into sentences and join
sentences within a chunk with a single space, flattening paragraph breaks.

**Task brief:** "Preserve punctuation and paragraph structure when passing narration text to
the Qwen3-TTS worker so the model can naturally interpret pauses, questions, emphasis, and
sentence boundaries."

**Resolution:** the chunker keeps the notebook's proven paragraph/sentence splitting and
greedy 80-word packing, but when packing sentences that belong to different paragraphs into
the same chunk it separates them with a blank line (`\n\n`) instead of a space, preserving
paragraph boundaries for the model. Punctuation is preserved exactly. Chunk boundaries still
respect paragraph breaks where possible. This is covered by unit tests.

## 3. Google OAuth requires user-supplied credentials

Google OAuth requires a registered OAuth client (`GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`) and an allowed redirect URI. These cannot be provisioned from this
environment. `.env.example` documents them. To allow the preview and automated tests to
exercise the full authenticated workflow without Google credentials, the backend exposes a
**dev login** (`GET /auth/dev-login?email=...`) that is disabled unless
`DEV_LOGIN=1` is set explicitly (never in production). Tests mock the Google token/userinfo
endpoints and also cover real session handling.

## 4. Mock worker returns synthetic WAVs

The mock worker emits deterministic tone WAVs (no `qwen-tts`, no GPU, no torch). It honors
the exact internal HTTP contract the real worker uses, including reporting `sample_rate`
per job. The backend records the worker's reported rate for cross-checking but treats the
sample rate parsed from the actual uploaded WAV chunks as **authoritative** for the final
narration (a mismatch is logged, never trusted) — see `backend/app/jobs.py` and the
sample-rate-authority test in `backend/tests/test_jobs_internal.py`.

## 5. Session cookie naming and hash-at-rest

Sessions store a SHA-256 hash of the random cookie token in SQLite (raw token only in the
browser cookie). Cookie is httpOnly + SameSite=Lax, and Secure when `COOKIE_SECURE=1`.

## 6. Worker payload carries binary artifacts inline

Narration jobs carry the `voice_clone_prompt.pt` bytes (base64) and clone-prompt jobs carry
the reference WAV bytes in the job payload rather than via object-storage URLs, so the
worker needs no storage credentials. Prompt `.pt` files are ~30 KB and reference clips a
few MB, acceptable for the internal API. Artifact uploads (per-chunk WAVs, and the design
preview WAV) use a single generic endpoint `POST /internal/jobs/{id}/artifact` with a
`field` parameter (`reference_audio`, `prompt_pt`, `chunk_<i>`), which refines the
`/internal/jobs/{id}/chunks` endpoint sketched in `docs/MVP_ARCHITECTURE.md` §3.3.

## 7. Reference audio passed to `create_voice_clone_prompt` as a temp-file path

**Verified fact (primary source):** the notebook (cell 21) calls
`clone_model.create_voice_clone_prompt(ref_audio=str(reference_path), ref_text=...)` —
the filesystem-path form, which `qwen-tts 0.1.1` loads via `librosa.load` (native sample
rate, mono). An `(np.ndarray, sr)` tuple is also supported by the API, but the path form is
the notebook-proven call.

**Resolution:** the GPU worker decodes the base64 reference clip to a temp WAV file and
passes `ref_audio=str(temp_path)`, exactly mirroring the notebook. This avoids the worker
having to reproduce `librosa`'s mono/resample behavior itself.

## 8. GPU-worker startup validation

The real worker (`--backend qwen`) runs `worker/qwen_tts_worker/checks.py` before polling:
torch presence, CUDA availability/device index, the pinned `qwen-tts==0.1.1` version and
its required API surface, and dtype validity. Failures are reported with actionable
messages and the worker exits with a non-zero code. This was added so a misconfigured GPU
host fails fast with a clear message instead of crashing later inside `from_pretrained`.
`qwen-tts==0.1.1` is the pinned, notebook-installed version; `transformers==4.57.3` and
`accelerate==1.12.0` are pinned because `qwen-tts==0.1.1` requires those exact versions
(evidence: notebook cell 7 install output).

## 9. One Qwen model resident at a time (VRAM not assumed)

The worker loads the Base model once for clone-prompt/narration jobs and loads the
VoiceDesign model only during a design job, then releases it with
`del` + `gc.collect()` + `torch.cuda.empty_cache()` (notebook cell 17 discipline). The
default `QWEN_KEEP_DESIGN_LOADED=false` means both 1.7B checkpoints are never held
simultaneously. No VRAM budget (e.g. "fits on a 16 GB T4") is claimed anywhere: that
remains unvalidated until the real GPU acceptance run.
