"""HTTP client for the backend internal job API.

The worker authenticates with a bearer token only; it never receives or uses
database/storage/OAuth credentials. Job ownership is bound with the claim token
minted at claim time and required back on artifact/complete/fail calls.
"""
import logging
from typing import Any

import httpx

from .config import WorkerConfig

logger = logging.getLogger("qwen-worker")


class WorkerAPIError(Exception):
    pass


class WorkerAPIClient:
    def __init__(
        self,
        config: WorkerConfig,
        transport: httpx.BaseTransport | None = None,
    ):
        self._config = config
        self._client = httpx.Client(
            base_url=config.backend_url,
            timeout=config.request_timeout_seconds,
            headers={
                "Authorization": f"Bearer {config.worker_token}",
                "User-Agent": "voice-studio-gpu-worker/0.1",
                # Capability gate: the backend only lets a worker claim/complete
                # jobs tagged for the backend it declares here (qwen | mock).
                "X-Worker-Backend": config.backend,
            },
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "WorkerAPIClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def poll(self) -> dict | None:
        resp = self._client.post("/internal/jobs/poll")
        if resp.status_code == 204:
            return None
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 401:
            raise WorkerAPIError("worker authentication rejected")
        raise WorkerAPIError(f"poll failed: HTTP {resp.status_code}: {resp.text[:200]}")

    def upload_artifact(self, job_id: str, field: str, data: bytes, claim_token: str) -> None:
        resp = self._client.post(
            f"/internal/jobs/{job_id}/artifact",
            headers={"X-Job-Claim-Token": claim_token},
            data={"field": field},
            files={"file": ("artifact.wav", data, "application/octet-stream")},
        )
        if resp.status_code != 200:
            raise WorkerAPIError(
                f"artifact upload failed for {field}: HTTP {resp.status_code}: {resp.text[:200]}"
            )

    def complete(
        self,
        job_id: str,
        claim_token: str,
        sample_rate: int | None = None,
        durations: list[float] | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if sample_rate is not None:
            body["sample_rate"] = int(sample_rate)
        if durations is not None:
            body["durations"] = durations
        resp = self._client.post(
            f"/internal/jobs/{job_id}/complete",
            headers={"X-Job-Claim-Token": claim_token},
            json=body,
        )
        if resp.status_code != 200:
            raise WorkerAPIError(
                f"complete failed: HTTP {resp.status_code}: {resp.text[:200]}"
            )

    def fail(self, job_id: str, claim_token: str, error: str) -> None:
        resp = self._client.post(
            f"/internal/jobs/{job_id}/fail",
            headers={"X-Job-Claim-Token": claim_token},
            json={"error": error[:4000]},
        )
        if resp.status_code != 200:
            raise WorkerAPIError(
                f"fail failed: HTTP {resp.status_code}: {resp.text[:200]}"
            )
