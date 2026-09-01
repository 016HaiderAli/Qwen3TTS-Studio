"""GPU worker entrypoint.

Usage (run from the repo's ``worker/`` directory so ``qwen_tts_worker`` is
importable):

    python -m qwen_tts_worker.main --backend mock     # no GPU required
    python -m qwen_tts_worker.main --backend qwen     # GPU host + qwen-tts

The worker polls the backend for jobs, dispatches to the configured inference
backend, uploads artifacts, and reports completion or failure. It processes one
job at a time (single GPU). For ``--backend qwen`` it first runs the GPU
environment checks in ``qwen_tts_worker.checks`` and aborts with actionable
errors if the host cannot run qwen-tts.
"""
import argparse
import logging
import sys
import time

import httpx

from . import checks
from .backends import InferenceBackend, MockBackend
from .client import WorkerAPIClient, WorkerAPIError
from .config import WorkerConfig

logger = logging.getLogger("qwen-worker")


def _build_backend(config: WorkerConfig) -> InferenceBackend:
    if config.backend == "mock":
        logger.info("Using mock backend (sample rate %d)", config.mock_sample_rate)
        return MockBackend(sample_rate=config.mock_sample_rate)
    if config.backend == "qwen":
        from .qwen_backend import QwenBackend

        logger.warning(
            "Using real Qwen3-TTS backend. GPU inference has NOT been validated "
            "in this environment; requires a CUDA GPU and qwen-tts installed."
        )
        return QwenBackend(config)
    raise ValueError(f"unknown backend: {config.backend}")


def _process_job(client: WorkerAPIClient, backend: InferenceBackend, claim: dict) -> None:
    job_id = claim["job_id"]
    job_type = claim["type"]
    payload = claim.get("payload") or {}
    claim_token = claim.get("claim_token") or ""
    logger.info(
        "Processing job %s (type=%s, backend=%s)",
        job_id, job_type, backend.name,
    )

    if job_type == "design":
        language = payload.get("language") or "English"
        instruct = payload.get("instruct") or ""
        text = payload.get("text") or ""
        logger.info(
            "design job %s: language=%s instruct=%r text=%r",
            job_id, language, instruct, text,
        )
        logger.info("design job %s: inference started", job_id)
        out = backend.design(language=language, instruct=instruct, text=text)
        logger.info(
            "design job %s: inference complete sr=%d duration=%.3fs bytes=%d",
            job_id, out.sample_rate, out.duration_sec, len(out.wav_bytes),
        )
        client.upload_artifact(job_id, "reference_audio", out.wav_bytes, claim_token)
        client.complete(
            job_id, claim_token, sample_rate=out.sample_rate, durations=[out.duration_sec],
        )
        logger.info("Job %s design succeeded", job_id)

    elif job_type == "clone_prompt":
        language = payload.get("language") or "English"
        ref_text = payload.get("ref_text") or ""
        ref_audio_b64 = payload.get("ref_audio_b64") or ""
        logger.info(
            "clone_prompt job %s: language=%s ref_text=%r ref_audio_b64_len=%d",
            job_id, language, ref_text, len(ref_audio_b64),
        )
        logger.info("clone_prompt job %s: inference started", job_id)
        pt_bytes = backend.create_clone_prompt(
            ref_audio_b64=ref_audio_b64, ref_text=ref_text, language=language,
        )
        logger.info(
            "clone_prompt job %s: inference complete bytes=%d",
            job_id, len(pt_bytes),
        )
        client.upload_artifact(job_id, "prompt_pt", pt_bytes, claim_token)
        client.complete(job_id, claim_token)
        logger.info("Job %s clone_prompt succeeded", job_id)

    elif job_type == "narration":
        chunks = payload.get("chunks") or []
        if not chunks:
            raise ValueError("narration job has no chunks")
        language = payload.get("language") or "English"
        instruct = payload.get("instruct") or ""
        voice_setting = payload.get("voice_setting") or None
        # Zero-shot path: ref_audio_b64 is present when the voice has no
        # pre-baked .pt yet; ref_text is the speaker's reference transcript.
        ref_audio_b64 = payload.get("ref_audio_b64") or ""
        ref_text = payload.get("ref_text") or "Voice cloning reference sample."
        logger.info(
            "narration job %s: language=%s instruct=%r chunks=%d "
            "has_prompt=%s has_ref_audio=%s voice_setting=%r",
            job_id, language, instruct, len(chunks),
            bool(payload.get("prompt_pt_b64")), bool(ref_audio_b64),
            voice_setting,
        )
        outputs = backend.narrate(
            chunks=chunks,
            prompt_pt_b64=payload.get("prompt_pt_b64") or "",
            ref_audio_b64=ref_audio_b64,
            ref_text=ref_text,
            language=language,
            instruct=instruct,
            voice_setting=voice_setting,
        )
        if len(outputs) != len(chunks):
            raise RuntimeError(
                f"expected {len(chunks)} outputs, got {len(outputs)}"
            )
        sample_rate = outputs[0].sample_rate
        durations = [o.duration_sec for o in outputs]
        for i, out in enumerate(outputs):
            logger.info(
                "narration job %s: chunk %d/%d sr=%d duration=%.3fs",
                job_id, i + 1, len(chunks), out.sample_rate, out.duration_sec,
            )
            client.upload_artifact(job_id, f"chunk_{i}", out.wav_bytes, claim_token)
        client.complete(
            job_id, claim_token, sample_rate=sample_rate, durations=durations,
        )
        logger.info("Job %s narration succeeded (%d chunks)", job_id, len(outputs))

    elif job_type == "custom_voice":
        chunks = payload.get("chunks") or []
        if not chunks:
            raise ValueError("custom_voice job has no chunks")
        speaker = payload.get("speaker") or ""
        language = payload.get("language") or "English"
        instruct = payload.get("instruct") or ""
        dialogue_segments = payload.get("dialogue_segments")
        voice_setting = payload.get("voice_setting") or None
        seg_count = len(dialogue_segments) if dialogue_segments else len(chunks)
        logger.info(
            "custom_voice job %s: speaker=%s language=%s instruct=%r segments=%d voice_setting=%r",
            job_id, speaker, language, instruct, seg_count, voice_setting,
        )
        outputs = backend.generate_custom_voice(
            chunks=chunks,
            speaker=speaker,
            language=language,
            instruct=instruct,
            dialogue_segments=dialogue_segments,
            voice_setting=voice_setting,
        )
        if len(outputs) != seg_count:
            raise RuntimeError(
                f"expected {seg_count} outputs, got {len(outputs)}"
            )
        sample_rate = outputs[0].sample_rate
        durations = [o.duration_sec for o in outputs]
        for i, out in enumerate(outputs):
            logger.info(
                "custom_voice job %s: chunk %d/%d sr=%d duration=%.3fs",
                job_id, i + 1, len(chunks), out.sample_rate, out.duration_sec,
            )
            client.upload_artifact(job_id, f"chunk_{i}", out.wav_bytes, claim_token)
        client.complete(
            job_id, claim_token, sample_rate=sample_rate, durations=durations,
        )
        logger.info("Job %s custom_voice succeeded (%d chunks)", job_id, len(outputs))

    else:
        raise ValueError(f"unknown job type: {job_type}")


def run_once(config: WorkerConfig, client: WorkerAPIClient, backend: InferenceBackend) -> bool:
    try:
        claim = client.poll()
    except httpx.HTTPError as exc:
        # Backend temporarily unreachable: log and retry on the next poll.
        logger.warning("Backend unreachable (%s); retrying...", exc)
        return False
    if claim is None:
        return False
    try:
        _process_job(client, backend, claim)
    except Exception as exc:  # report failure and keep the loop alive
        logger.exception("job %s failed", claim.get("job_id"))
        # str(exc) is empty for bare exception types (e.g. EOFError(), TypeError())
        # which would fail the backend's FailRequest min_length=1 validation and
        # raise a secondary WorkerAPIError that silences the original error.
        err_msg = str(exc) or repr(exc) or "Unknown worker execution error"
        try:
            client.fail(
                claim.get("job_id"),
                claim.get("claim_token") or "",
                err_msg,
            )
        except WorkerAPIError:
            logger.exception("could not report failure for job %s", claim.get("job_id"))
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voice Studio GPU worker")
    parser.add_argument(
        "--backend",
        choices=["mock", "qwen"],
        default=None,
        help="inference backend (default: env WORKER_BACKEND, else mock)",
    )
    parser.add_argument("--once", action="store_true", help="process a single job and exit")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = WorkerConfig.from_env()
    if args.backend:
        config.backend = args.backend

    if not config.worker_token:
        logger.error("WORKER_TOKEN is required")
        return 2

    if config.backend == "qwen":
        results = checks.run_startup_checks(config)
        failed = [r for r in results if not r.ok]
        if failed:
            logger.error(
                "GPU worker startup aborted: %d check(s) failed (see above). "
                "Fix the environment, or use --backend mock for the GPU-less preview flow.",
                len(failed),
            )
            return 3

    backend = _build_backend(config)
    if backend.name == "qwen":
        logger.info(
            "Qwen backend configured: design_model=%s base_model=%s device=%s dtype=%s",
            config.qwen_model_design,
            config.qwen_model_base,
            config.qwen_device,
            config.qwen_dtype,
        )
    client = WorkerAPIClient(config)

    try:
        if args.once:
            run_once(config, client, backend)
            return 0
        logger.info(
            "Worker ready (backend=%s, polling %s every %.1fs)",
            backend.name,
            config.backend_url,
            config.poll_interval_seconds,
        )
        while True:
            processed = run_once(config, client, backend)
            if not processed:
                time.sleep(config.poll_interval_seconds)
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except WorkerAPIError as exc:
        logger.error("Fatal worker error: %s", exc)
        return 1
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
