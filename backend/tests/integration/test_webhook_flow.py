"""GitHub webhook 入口测试：验签 / 事件过滤 / 入队。

commit status 的 pending 调用用 AsyncMock 替身；ARQ 入队用 conftest 的 fake_arq
（webhook 路由已改用 ArqPoolDep 注入，故 fake_arq 能生效）。
"""

import hashlib
import hmac
import json
from unittest.mock import AsyncMock

import pytest

from app.core.config import get_settings
from app.platform.adapters.github import GitHubAdapter

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_SECRET = "test-webhook-secret"


@pytest.fixture(autouse=True)
def webhook_env(monkeypatch):
    """配上 github_webhook_secret（默认空会跳过验签），并 mock pending status 调用。"""
    monkeypatch.setattr(get_settings(), "github_webhook_secret", _SECRET)
    monkeypatch.setattr(GitHubAdapter, "set_commit_status", AsyncMock())


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _pr_payload(repo_url: str, *, action: str = "opened", pr: int = 7, sha: str = "f" * 40) -> bytes:
    return json.dumps({
        "action": action,
        "pull_request": {"number": pr, "head": {"sha": sha}},
        "repository": {"html_url": repo_url, "language": "Python"},
    }).encode()


async def _post(client, body: bytes, *, sig: str | None, event: str = "pull_request"):
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if sig is not None:
        headers["X-Hub-Signature-256"] = sig
    return await client.post("/api/v1/webhooks/github", content=body, headers=headers)


# ── 验签 ──────────────────────────────────────────────────────────────────────

async def test_valid_signature_accepted_and_enqueued(http_client, github_repo):
    body = _pr_payload(github_repo.url)
    resp = await _post(http_client, body, sig=_sign(body))
    assert resp.status_code == 202
    assert resp.json()["status"] == "accepted"
    http_client.fake_arq.enqueue_job.assert_awaited_once()


async def test_invalid_signature_rejected(http_client, github_repo):
    body = _pr_payload(github_repo.url)
    resp = await _post(http_client, body, sig="sha256=deadbeef")
    assert resp.status_code == 401
    http_client.fake_arq.enqueue_job.assert_not_awaited()


async def test_missing_signature_rejected(http_client, github_repo):
    body = _pr_payload(github_repo.url)
    resp = await _post(http_client, body, sig=None)
    assert resp.status_code == 401
    http_client.fake_arq.enqueue_job.assert_not_awaited()


# ── 事件 / action 过滤 ────────────────────────────────────────────────────────

async def test_non_pull_request_event_ignored(http_client):
    body = _pr_payload("https://github.com/x/y")
    resp = await _post(http_client, body, sig=_sign(body), event="push")
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"
    http_client.fake_arq.enqueue_job.assert_not_awaited()


async def test_non_whitelisted_action_ignored(http_client, github_repo):
    body = _pr_payload(github_repo.url, action="closed")
    resp = await _post(http_client, body, sig=_sign(body))
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"
    http_client.fake_arq.enqueue_job.assert_not_awaited()


async def test_unregistered_repo_ignored(http_client):
    body = _pr_payload("https://github.com/nobody/unknown-repo")
    resp = await _post(http_client, body, sig=_sign(body))
    assert resp.status_code == 202
    assert resp.json()["status"] == "ignored"
    assert "not registered" in resp.json()["reason"]
    http_client.fake_arq.enqueue_job.assert_not_awaited()
