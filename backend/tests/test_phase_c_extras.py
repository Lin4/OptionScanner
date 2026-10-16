"""Phase C — Track record, Smart alerts, Learn/levels (OptiScreen iteration 9)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("EXPO_PUBLIC_BACKEND_URL", "https://optionscope.preview.emergentagent.com").rstrip("/")
EMAIL = "trader@optiscreen.app"
PASSWORD = "TestPass123!"


@pytest.fixture(scope="session")
def token():
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=20)
    assert r.status_code == 200, r.text
    return r.json()["session_token"]


@pytest.fixture(scope="session")
def auth(token):
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ------------------------------------------------- track record
class TestTrackRecord:
    def test_best_options_logs_picks(self, auth):
        r = requests.post(
            f"{BASE_URL}/api/screener/best-options",
            headers=auth,
            json={"profile": "low_low", "days_to_exp": 30},
            timeout=60,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert "results" in data
        # trigger a 2nd call to verify dedup (same key -> no new picks)
        requests.post(
            f"{BASE_URL}/api/screener/best-options",
            headers=auth,
            json={"profile": "low_low", "days_to_exp": 30},
            timeout=60,
        )
        time.sleep(2)  # background task

    def test_track_record_shape(self, auth):
        r = requests.get(f"{BASE_URL}/api/track-record", headers=auth, timeout=20)
        assert r.status_code == 200, r.text
        tr = r.json()
        assert "live" in tr and "backtest" in tr
        live = tr["live"]
        for k in ("stats", "buckets", "settled", "open", "open_count", "method"):
            assert k in live, f"missing live.{k}"
        assert isinstance(live["buckets"], list) and len(live["buckets"]) == 3
        assert {b["range"] for b in live["buckets"]} == {"70–80%", "80–90%", "90–100%"}
        # open picks should be >0 after screener call above
        assert live["open_count"] >= 1
        assert tr["backtest"].get("status") in ("ready", "pending")

    def test_backtest_ready_after_wait(self, auth):
        # backtest kicks in ~90s after backend start; poll up to 120s
        for _ in range(24):
            r = requests.get(f"{BASE_URL}/api/track-record", headers=auth, timeout=20)
            bt = r.json()["backtest"]
            if bt.get("status") == "ready":
                for k in ("stats", "buckets", "by_strategy", "recent", "method"):
                    assert k in bt, f"missing backtest.{k}"
                assert {b["range"] for b in bt["buckets"]} == {"70–80%", "80–90%", "90–100%"}
                return
            time.sleep(5)
        pytest.skip("Backtest still pending after 120s — expected on cold start if candle fetch slow")


# ------------------------------------------------- smart alerts
class TestSmartAlerts:
    smart_id = None

    def test_add_smart_setup_without_threshold(self, auth):
        r = requests.post(
            f"{BASE_URL}/api/alerts/add",
            headers=auth,
            json={"ticker": "ALL", "kind": "smart_setup", "note": "low_low"},
            timeout=20,
        )
        assert r.status_code == 200, r.text
        a = r.json()
        assert a["kind"] == "smart_setup"
        assert a["note"] == "low_low"
        assert a["threshold"] is None
        TestSmartAlerts.smart_id = a["alert_id"]

    def test_smart_check_without_alert_returns_400(self, auth):
        # remove the alert, try again, 400
        if TestSmartAlerts.smart_id:
            requests.delete(f"{BASE_URL}/api/alerts/{TestSmartAlerts.smart_id}", headers=auth, timeout=10)
        r = requests.post(f"{BASE_URL}/api/alerts/smart/check", headers=auth, timeout=30)
        assert r.status_code == 400, r.text
        # re-create for subsequent tests
        r2 = requests.post(
            f"{BASE_URL}/api/alerts/add",
            headers=auth,
            json={"ticker": "ALL", "kind": "smart_setup", "note": "low_low"},
            timeout=20,
        )
        TestSmartAlerts.smart_id = r2.json()["alert_id"]

    def test_smart_check_caps_at_3_per_day(self, auth):
        # clear any smart events for a clean count
        totals = 0
        last = []
        for _ in range(5):
            r = requests.post(f"{BASE_URL}/api/alerts/smart/check", headers=auth, timeout=60)
            assert r.status_code == 200, r.text
            new = r.json()["new"]
            totals += len(new)
            last = new
        # over 5 runs, total new events today must never exceed 3
        feed = requests.get(f"{BASE_URL}/api/alerts/feed", headers=auth, timeout=10).json()
        # count today's smart events in feed
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        ny_today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
        today_count = sum(1 for it in feed["items"] if it.get("kind") == "smart_setup" and (it.get("created_at", "")[:10] >= ny_today))
        assert today_count <= 3, f"Expected <=3 smart events today, got {today_count}"
        # pop level gating: pop >=70, strategy allowed for level 3 (not naked)
        for ev in feed["items"][:10]:
            if ev.get("kind") == "smart_setup":
                assert ev["pop"] >= 70
                assert ev["strategy"] not in ("Sell Put", "Sell Call", "Short Strangle")

    def test_alerts_feed_shape(self, auth):
        r = requests.get(f"{BASE_URL}/api/alerts/feed", headers=auth, timeout=10)
        assert r.status_code == 200, r.text
        f = r.json()
        assert "items" in f and "max_per_day" in f and "market_open" in f
        assert f["max_per_day"] == 3

    def test_cleanup_smart_alert(self, auth):
        if TestSmartAlerts.smart_id:
            r = requests.delete(f"{BASE_URL}/api/alerts/{TestSmartAlerts.smart_id}", headers=auth, timeout=10)
            assert r.status_code == 200


# ------------------------------------------------- learn / levels
class TestLearn:
    def test_levels_list(self, auth):
        r = requests.get(f"{BASE_URL}/api/learn/levels", headers=auth, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "levels" in d and "options_level" in d and "note" in d
        assert len(d["levels"]) == 4
        # user is level 3 — unlocked_for_trading true for 1,2,3; false for 4
        by_num = {L["level"]: L for L in d["levels"]}
        assert by_num[1]["unlocked_for_trading"] is True
        assert by_num[3]["unlocked_for_trading"] is True
        assert by_num[4]["unlocked_for_trading"] is False
        for L in d["levels"]:
            assert "passed" in L and "best_score" in L and "quiz_len" in L and L["quiz_len"] == 3

    @pytest.mark.parametrize("lvl", [1, 2, 3, 4])
    def test_level_detail_hides_answers(self, auth, lvl):
        r = requests.get(f"{BASE_URL}/api/learn/levels/{lvl}", headers=auth, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["level"] == lvl
        assert len(d["lessons"]) >= 1
        assert len(d["quiz"]) == 3
        for q in d["quiz"]:
            assert "q" in q and "options" in q
            assert "answer" not in q and "explain" not in q

    def test_level_404(self, auth):
        r = requests.get(f"{BASE_URL}/api/learn/levels/9", headers=auth, timeout=10)
        assert r.status_code == 404

    @pytest.mark.parametrize("lvl,ans", [(1, [0, 2, 1]), (2, [1, 0, 1]), (3, [1, 1, 0]), (4, [2, 1, 1])])
    def test_quiz_correct(self, auth, lvl, ans):
        r = requests.post(f"{BASE_URL}/api/learn/levels/{lvl}/quiz", headers=auth, json={"answers": ans}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["score"] == 3
        assert d["total"] == 3
        assert d["passed"] is True
        for res in d["results"]:
            assert res["correct"] is True

    def test_quiz_wrong_returns_explanations(self, auth):
        r = requests.post(f"{BASE_URL}/api/learn/levels/1/quiz", headers=auth, json={"answers": [1, 1, 0]}, timeout=10)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["passed"] is False
        for res in d["results"]:
            assert "answer" in res and "explain" in res

    def test_quiz_wrong_length_400(self, auth):
        r = requests.post(f"{BASE_URL}/api/learn/levels/1/quiz", headers=auth, json={"answers": [0, 2]}, timeout=10)
        assert r.status_code == 400

    def test_quiz_unknown_level_404(self, auth):
        r = requests.post(f"{BASE_URL}/api/learn/levels/9/quiz", headers=auth, json={"answers": [0, 2, 1]}, timeout=10)
        assert r.status_code == 404

    def test_passed_level_recorded_in_list(self, auth):
        r = requests.get(f"{BASE_URL}/api/learn/levels", headers=auth, timeout=10)
        by_num = {L["level"]: L for L in r.json()["levels"]}
        # we passed all 4 above
        for n in (1, 2, 3, 4):
            assert by_num[n]["passed"] is True
            assert by_num[n]["best_score"] == 3


# ------------------------------------------------- cleanup lesson progress (optional per note)
class TestZZCleanup:
    def test_cleanup_lesson_progress(self, auth):
        # cleanup lesson_progress & alert_events for this user via Mongo would need direct access;
        # skipping explicit cleanup — test data is clearly identifiable by trader user_id.
        pass
