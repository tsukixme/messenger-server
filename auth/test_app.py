"""
Тесты сервиса входа. Запуск: cd auth && python3 -m pytest test_app.py -v

Перед импортом app.py задаём переменные окружения — сам app.py на старте
проверяет их (в частности, требует WA_APP_SECRET при DEV_MODE=false), а
Python выполняет этот код один раз, в момент первого импорта.
Все внешние вызовы (Synapse, WhatsApp) замоканы — реальная сеть не используется.
"""
import hashlib
import hmac
import json
import os
import tempfile
from unittest.mock import AsyncMock

os.environ.setdefault("SERVER_NAME", "test.example")
os.environ.setdefault("SYNAPSE_ADMIN_TOKEN", "test-admin-token")
os.environ.setdefault("WA_APP_SECRET", "test-secret")
os.environ.setdefault("WA_BUSINESS_NUMBER", "15551234567")
os.environ.setdefault("DEV_MODE", "false")
os.environ.setdefault("DB_PATH", tempfile.NamedTemporaryFile(suffix=".db", delete=False).name)

import httpx
import pytest

import app  # noqa: E402


@pytest.fixture(autouse=True)
async def _clean_db():
    """Каждый тест начинает с пустой базы, чтобы тесты не влияли друг на друга."""
    await app.db.wipe()
    app._ip_starts.clear()
    yield


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _signed_webhook_body(sender: str, text: str) -> tuple[bytes, str]:
    payload = {
        "entry": [{"changes": [{"value": {"messages": [
            {"type": "text", "from": sender, "text": {"body": text}}
        ]}}]}]
    }
    raw = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(app.WA_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return raw, signature


# ---------- базовый сценарий ----------

async def test_start_creates_session_and_returns_code(client):
    r = await client.post("/auth/start", json={"phone": "+7 701 123 45 67"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["code"]) == 6
    assert body["session_id"]
    assert "wa.me" in body["wa_link"]


async def test_start_rejects_invalid_phone(client):
    r = await client.post("/auth/start", json={"phone": "abc"})
    assert r.status_code == 400


async def test_status_pending_until_verified(client):
    r = await client.post("/auth/start", json={"phone": "77011111111"})
    sid = r.json()["session_id"]
    r2 = await client.get(f"/auth/status/{sid}")
    assert r2.status_code == 200
    assert r2.json() == {"verified": False}


async def test_status_unknown_session_returns_410(client):
    r = await client.get("/auth/status/does-not-exist")
    assert r.status_code == 410


# ---------- подтверждение через webhook ----------

async def test_webhook_rejects_missing_signature(client):
    raw, _ = _signed_webhook_body("77012222222", "000000")
    r = await client.post("/auth/webhook", content=raw)
    assert r.status_code == 403


async def test_webhook_rejects_wrong_signature(client):
    raw, _ = _signed_webhook_body("77012222222", "000000")
    r = await client.post(
        "/auth/webhook", content=raw, headers={"X-Hub-Signature-256": "sha256=wrong"}
    )
    assert r.status_code == 403


async def test_webhook_accepts_correct_signature_and_confirms_matching_phone(client, monkeypatch):
    monkeypatch.setattr(
        app, "ensure_matrix_user", AsyncMock(return_value=("@u77013333333:test.example", "pw"))
    )
    start_r = await client.post("/auth/start", json={"phone": "77013333333"})
    code = start_r.json()["code"]
    sid = start_r.json()["session_id"]

    raw, sig = _signed_webhook_body("77013333333", f"Код {code}")
    webhook_r = await client.post("/auth/webhook", content=raw, headers={"X-Hub-Signature-256": sig})
    assert webhook_r.status_code == 200

    status_r = await client.get(f"/auth/status/{sid}")
    assert status_r.json() == {
        "verified": True, "user_id": "@u77013333333:test.example", "password": "pw",
    }


async def test_webhook_ignores_code_from_wrong_sender(client):
    start_r = await client.post("/auth/start", json={"phone": "77014444444"})
    code = start_r.json()["code"]
    sid = start_r.json()["session_id"]

    raw, sig = _signed_webhook_body("77019999999", f"Код {code}")  # чужой номер
    await client.post("/auth/webhook", content=raw, headers={"X-Hub-Signature-256": sig})

    status_r = await client.get(f"/auth/status/{sid}")
    assert status_r.json() == {"verified": False}


# ---------- dev-режим ----------

async def test_dev_message_disabled_when_dev_mode_false(client):
    r = await client.post("/auth/dev/message", json={"phone": "77015555555", "text": "000000"})
    assert r.status_code == 404


# ---------- ограничения на злоупотребления ----------

async def test_start_rate_limited_after_5_attempts_per_phone(client):
    phone = "77016666666"
    for _ in range(5):
        r = await client.post("/auth/start", json={"phone": phone})
        assert r.status_code == 200
    r = await client.post("/auth/start", json={"phone": phone})
    assert r.status_code == 429


async def test_start_rate_limited_per_ip_across_different_phones(client):
    for i in range(app.MAX_STARTS_PER_IP_HOUR):
        r = await client.post("/auth/start", json={"phone": f"7700000{i:04d}"})
        assert r.status_code == 200
    r = await client.post("/auth/start", json={"phone": "77019990000"})
    assert r.status_code == 429


# ---------- устойчивость к сбою Synapse ----------

async def test_session_survives_matrix_failure_and_succeeds_on_retry(client, monkeypatch):
    start_r = await client.post("/auth/start", json={"phone": "77017777777"})
    code = start_r.json()["code"]
    sid = start_r.json()["session_id"]
    raw, sig = _signed_webhook_body("77017777777", f"Код {code}")
    await client.post("/auth/webhook", content=raw, headers={"X-Hub-Signature-256": sig})

    monkeypatch.setattr(
        app, "ensure_matrix_user", AsyncMock(side_effect=app.HTTPException(502, "Synapse недоступен"))
    )
    first = await client.get(f"/auth/status/{sid}")
    assert first.status_code == 502

    monkeypatch.setattr(
        app, "ensure_matrix_user", AsyncMock(return_value=("@u77017777777:test.example", "pw2"))
    )
    second = await client.get(f"/auth/status/{sid}")
    assert second.status_code == 200
    assert second.json()["verified"] is True


async def test_status_returns_credentials_once_then_410(client, monkeypatch):
    monkeypatch.setattr(
        app, "ensure_matrix_user", AsyncMock(return_value=("@u77018888888:test.example", "pw3"))
    )
    start_r = await client.post("/auth/start", json={"phone": "77018888888"})
    code = start_r.json()["code"]
    sid = start_r.json()["session_id"]
    raw, sig = _signed_webhook_body("77018888888", f"Код {code}")
    await client.post("/auth/webhook", content=raw, headers={"X-Hub-Signature-256": sig})

    first = await client.get(f"/auth/status/{sid}")
    assert first.json()["verified"] is True
    second = await client.get(f"/auth/status/{sid}")
    assert second.status_code == 410
