"""Unit tests for the worker HTTP client using httpx.MockTransport."""
import httpx
import pytest

from qwen_tts_worker.client import WorkerAPIClient, WorkerAPIError
from qwen_tts_worker.config import WorkerConfig


def _client(handler) -> WorkerAPIClient:
    cfg = WorkerConfig(
        backend_url="http://test", worker_token="tok", request_timeout_seconds=5
    )
    transport = httpx.MockTransport(handler)
    return WorkerAPIClient(cfg, transport=transport)


def test_poll_returns_none_on_204():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/jobs/poll"
        assert request.headers["authorization"] == "Bearer tok"
        assert request.headers["x-worker-backend"] == "mock"
        return httpx.Response(204)

    with _client(handler) as client:
        assert client.poll() is None


def test_declares_configured_backend_capability():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["backend"] = request.headers["x-worker-backend"]
        return httpx.Response(204)

    cfg = WorkerConfig(
        backend_url="http://test",
        worker_token="tok",
        backend="qwen",
        request_timeout_seconds=5,
    )
    with WorkerAPIClient(cfg, transport=httpx.MockTransport(handler)) as client:
        client.poll()
    assert captured["backend"] == "qwen"


def test_poll_returns_claim():
    def handler(request):
        return httpx.Response(200, json={"job_id": "j1", "type": "design", "payload": {}})

    with _client(handler) as client:
        claim = client.poll()
        assert claim["job_id"] == "j1"
        assert claim["type"] == "design"


def test_poll_401_raises():
    def handler(request):
        return httpx.Response(401)

    with _client(handler) as client:
        with pytest.raises(WorkerAPIError):
            client.poll()


def test_upload_artifact_multipart():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url.path
        captured["content"] = request.content
        return httpx.Response(200, json={"field": "chunk_0", "stored": True})

    with _client(handler) as client:
        client.upload_artifact("job1", "chunk_0", b"wav-bytes")
    assert captured["url"] == "/internal/jobs/job1/artifact"
    assert b"wav-bytes" in captured["content"]
    assert b'name="field"' in captured["content"]


def test_complete_posts_body():
    captured = {}

    def handler(request):
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        client.complete("job1", sample_rate=24000, durations=[1.5])
    assert b'"sample_rate":24000' in captured["body"]
    assert b"1.5" in captured["body"]


def test_fail_posts_error():
    captured = {}

    def handler(request):
        captured["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    with _client(handler) as client:
        client.fail("job1", "boom")
    assert b'"error"' in captured["body"]
    assert b"boom" in captured["body"]


def test_complete_error_raises():
    def handler(request):
        return httpx.Response(409, text="Job is not running.")

    with _client(handler) as client:
        with pytest.raises(WorkerAPIError):
            client.complete("job1")
