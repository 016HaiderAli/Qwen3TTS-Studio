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
- **Narration generation** preserves punctuation and paragraph structure verbatim when
  passing each chunk to `generate_voice_clone`. This is the Base model's documented native
  expressive path ("adaptive control of tone, speaking rate, and emotional expression based
  on ... text semantics"; robust handling of punctuation/pauses). Paragraph boundaries are
  preserved inside chunks with blank-line separators (notebook cells 46/55 flatten them;
  see deviation 2).
- The real GPU worker performs a **capability probe** on the installed
  `generate_voice_clone`: if a future `qwen-tts` version exposes an instruction parameter,
  the delivery direction is forwarded to it. If not, the direction is logged and the native
  prosody path is used. The worker never passes an unsupported keyword argument.
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
per job (the backend stores whatever the worker reports and never assumes a fixed rate).

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
