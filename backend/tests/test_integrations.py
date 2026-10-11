"""
Integration tests for OptiScreen: Push, ElevenLabs TTS/STT, PayPal.
Does NOT modify .env; EMERGENT_PUSH_KEY=placeholder is expected to upstream-401 and must
be gracefully surfaced as {ok:false, error:...} by the push test endpoints.
"""
import os
import struct
import wave
import io
import pytest
import requests

BASE_URL = "https://optionscope.preview.emergentagent.com"


# -------- helpers --------
def _wav_bytes(seconds=0.5, sr=16000, freq=440.0) -> bytes:
    import math
    n = int(seconds * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            v = int(32767 * 0.3 * math.sin(2 * math.pi * freq * (i / sr)))
            frames += struct.pack("<h", v)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _assert_no_mongo_id(obj):
    if isinstance(obj, dict):
        assert "_id" not in obj, f"_id leaked: {obj.keys()}"
        for v in obj.values():
            _assert_no_mongo_id(v)
    elif isinstance(obj, list):
        for v in obj:
            _assert_no_mongo_id(v)


# =============================================================
# Push Notifications
# =============================================================
class TestPushNotifications:
    def test_register_push_accepts_body(self, api):
        """POST /api/register-push - should not 404/422; may 500 due to placeholder key."""
        body = {"user_id": "test-user-1", "platform": "ios", "device_token": "TEST_dummy_token_abc123"}
        r = api.post(f"{BASE_URL}/api/register-push", json=body, timeout=20)
        # Endpoint exists and accepts body. Placeholder key will cause upstream 401 -> 500 (per playbook).
        assert r.status_code in (201, 200, 500, 502), f"unexpected: {r.status_code} {r.text[:200]}"
        if r.status_code in (200, 201):
            _assert_no_mongo_id(r.json())

    def test_register_push_bad_body(self, api):
        r = api.post(f"{BASE_URL}/api/register-push", json={"platform": "ios"}, timeout=10)
        assert r.status_code == 422

    def test_push_test_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/push/test", json={}, timeout=10)
        assert r.status_code == 401

    def test_push_test_no_crash_with_placeholder(self, api, auth_headers):
        """Should NOT 500. With placeholder key, returns {ok:false, error:...}."""
        r = api.post(f"{BASE_URL}/api/push/test",
                     json={"title": "Hi", "message": "Test"},
                     headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:200]}"
        data = r.json()
        assert "ok" in data
        if data["ok"] is False:
            assert "error" in data and data["error"]

    def test_push_daily_pick_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/push/daily-pick", timeout=10)
        assert r.status_code == 401

    def test_push_daily_pick_graceful(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/push/daily-pick", headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        assert "ok" in data and "ticker" in data
        assert isinstance(data["ticker"], str) and data["ticker"]

    def test_push_earnings_reminder_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/push/earnings-reminder",
                     json={"ticker": "AAPL", "earnings_date": "2026-02-01"}, timeout=10)
        assert r.status_code == 401

    def test_push_earnings_reminder_graceful(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/push/earnings-reminder",
                     json={"ticker": "AAPL", "earnings_date": "2026-02-01"},
                     headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        assert "ok" in data


# =============================================================
# ElevenLabs TTS / STT
# =============================================================
class TestElevenLabs:
    def test_tts_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/tts/generate", json={"text": "Hello"}, timeout=10)
        assert r.status_code == 401

    def test_tts_generates_audio(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/tts/generate",
                     json={"text": "Apple looks strong today"},
                     headers=auth_headers, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        assert "audio_url" in data
        assert data["audio_url"].startswith("data:audio/mpeg;base64,")
        b64 = data["audio_url"].split(",", 1)[1]
        assert len(b64) > 1000, f"audio too small: {len(b64)}"
        _assert_no_mongo_id(data)

    def test_stt_requires_auth(self, api):
        files = {"audio": ("x.wav", b"RIFF0000WAVE", "audio/wav")}
        r = requests.post(f"{BASE_URL}/api/stt/transcribe", files=files, timeout=10)
        assert r.status_code == 401

    def test_stt_transcribe_wav(self, api, seed_token):
        wav = _wav_bytes(0.6)
        files = {"audio": ("test.wav", wav, "audio/wav")}
        headers = {"Authorization": f"Bearer {seed_token}"}
        r = requests.post(f"{BASE_URL}/api/stt/transcribe", files=files, headers=headers, timeout=30)
        assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
        data = r.json()
        assert "text" in data
        assert isinstance(data["text"], str)


# =============================================================
# PayPal (sandbox)
# =============================================================
class TestPayPal:
    def test_paypal_config_public(self, api):
        r = api.get(f"{BASE_URL}/api/paypal/config", timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data.get("mode") == "sandbox"
        assert data.get("client_id"), "client_id must be non-empty"
        assert len(data["client_id"]) > 20

    def test_create_order_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/paypal/create-order", json={"plan": "simple"}, timeout=10)
        assert r.status_code == 401

    def test_create_order_simple(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/paypal/create-order",
                     json={"plan": "simple"}, headers=auth_headers, timeout=25)
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        data = r.json()
        assert data.get("plan") == "simple"
        assert data.get("amount") == "9.00"
        assert data.get("order_id")
        assert data.get("approve_url", "").startswith("https://www.sandbox.paypal.com"), \
            f"approve_url={data.get('approve_url')}"
        _assert_no_mongo_id(data)

    def test_create_order_advance(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/paypal/create-order",
                     json={"plan": "advance"}, headers=auth_headers, timeout=25)
        assert r.status_code == 200
        data = r.json()
        assert data["amount"] == "29.00"
        assert data["approve_url"].startswith("https://www.sandbox.paypal.com")

    def test_create_order_expert(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/paypal/create-order",
                     json={"plan": "expert"}, headers=auth_headers, timeout=25)
        assert r.status_code == 200
        assert r.json()["amount"] == "79.00"

    def test_create_order_invalid_plan(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/paypal/create-order",
                     json={"plan": "ultra"}, headers=auth_headers, timeout=15)
        assert r.status_code == 400

    def test_capture_order_bogus_id(self, api, auth_headers):
        """Bogus order_id must surface as 502 (PayPal upstream error), not 500/200."""
        r = api.post(f"{BASE_URL}/api/paypal/capture-order",
                     json={"order_id": "BOGUS_ORDER_XYZ_123"}, headers=auth_headers, timeout=25)
        assert r.status_code in (400, 404, 502), f"{r.status_code} {r.text[:200]}"

    def test_capture_requires_auth(self, api):
        r = api.post(f"{BASE_URL}/api/paypal/capture-order", json={"order_id": "x"}, timeout=10)
        assert r.status_code == 401


# =============================================================
# Regression: existing endpoints still work
# =============================================================
class TestRegression:
    def test_login_still_works(self, api):
        r = api.post(f"{BASE_URL}/api/auth/login",
                     json={"email": "trader@optiscreen.app", "password": "TestPass123!"}, timeout=15)
        assert r.status_code == 200
        data = r.json()
        assert "session_token" in data
        assert data["user"]["email"] == "trader@optiscreen.app"
        _assert_no_mongo_id(data)

    def test_best_options_still_works(self, api, auth_headers):
        r = api.post(f"{BASE_URL}/api/screener/best-options",
                     json={"period": "week", "limit": 3}, headers=auth_headers, timeout=45)
        assert r.status_code == 200
        data = r.json()
        assert "results" in data and len(data["results"]) == 3
        for res in data["results"]:
            assert "ticker" in res and "strategy" in res and "annual_pct_no_margin" in res
        _assert_no_mongo_id(data)
