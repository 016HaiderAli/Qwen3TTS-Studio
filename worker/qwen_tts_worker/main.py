"""GPU worker entrypoint.

Usage:
    python -m qwen_tts_worker.main --backend mock     # no GPU required
    python -m qwen_tts_worker.main --backend qwen     # GPU host + qwen-tts

The worker polls the backend for jobs, dispatches to the configured inference
backend, uploads artifacts, and reports completion or failure. It processes one
job at a time (single GPU).
"""
import argparse
import logging
import sys
import time

import httpx

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
    logger.info("Processing job %s (type=%s)", job_id, job_type)

    if job_type == "design":
        out = backend.design(
            language=payload.get("language") or "English",
            instruct=payload.get("instruct") or "",
            text=payload.get("text") or "",
        )
        client.upload_artifact(job_id, "reference_audio", out.wav_bytes)
        client.complete(job_id, sample_rate=out.sample_rate, durations=[out.duration_sec])
        logger.info("Job %s design complete (%.2fs)", job_id, out.duration_sec)

    elif job_type == "clone_prompt":
        pt_bytes = backend.create_clone_prompt(
            ref_audio_b64=payload.get("ref_audio_b64") or "",
            ref_text=payload.get("ref_text") or "",
            language=payload.get("language") or "English",
        )
        client.upload_artifact(job_id, "prompt_pt", pt_bytes)
        client.complete(job_id)
        logger.info("Job %s clone prompt complete (%d bytes)", job_id, len(pt_bytes))

    elif job_type == "narration":
        chunks = payload.get("chunks") or []
        if not chunks:
            raise ValueError("narration job has no chunks")
        outputs = backend.narrate(
            chunks=chunks,
            prompt_pt_b64=payload.get("prompt_pt_b64") or "",
            language=payload.get("language") or "English",
            instruct=payload.get("instruct") or "",
        )
        if len(outputs) != len(chunks):
            raise RuntimeError(
                f"expected {len(chunks)} outputs, got {len(outputs)}"
            )
        sample_rate = outputs[0].sample_rate
        durations = [o.duration_sec for o in outputs]
        for i, out in enumerate(outputs):
            client.upload_artifact(job_id, f"chunk_{i}", out.wav_bytes)
        client.complete(job_id, sample_rate=sample_rate, durations=durations)
        logger.info("Job %s narration complete (%d chunks)", job_id, len(outputs))

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
        try:
            client.fail(claim.get("job_id"), str(exc))
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
    if config.backend == "qwen" and config.requires_gpu:
        logger.info("backend=qwen requires a CUDA GPU at runtime")

    backend = _build_backend(config)
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
