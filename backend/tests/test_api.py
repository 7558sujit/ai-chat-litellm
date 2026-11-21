import os
import tempfile
from types import SimpleNamespace

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/t.db"
os.environ["LLM_API_KEYS"] = "k1,k2"
os.environ["ENABLE_FAILURE_SIMULATION"] = "true"

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.main import app

STATE = {"fail": set(), "seen": [], "cache": {}}


async def fake(model, messages, api_key, bypass_cache):
    if api_key in STATE["fail"]:
        raise RuntimeError("429")
    STATE["seen"].append(messages)
    ck = (model, str(messages))
    hit = ck in STATE["cache"] and not bypass_cache
    text = STATE["cache"].get(ck) if hit else f"echo:{messages[-1]['content']}"
    STATE["cache"][ck] = text
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3),
        _hidden_params={"cache_hit": hit},
    )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(llm, "_completion", fake)
    STATE.update(fail=set(), seen=[], cache={})
    with TestClient(app) as c:
        yield c


def chat(c, sid, msg, **h):
    return c.post("/chat", json={"session_id": sid, "message": msg}, headers=h)


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_history_and_multiturn(client):
    r = chat(client, "a1", "hello").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE" and r["metadata"]["key_id"] == "key_1"
    chat(client, "a1", "again")
    assert len(STATE["seen"][-1]) == 4  # system + user + assistant + new user
    h = client.get("/sessions/a1/messages").json()["messages"]
    assert [m["role"] for m in h] == ["user", "assistant", "user", "assistant"]


def test_sessions_isolated(client):
    chat(client, "s1", "one")
    chat(client, "s2", "two")
    assert len(client.get("/sessions/s2/messages").json()["messages"]) == 2


def test_cache_hit_across_sessions(client):
    a = chat(client, "c1", "capital of france").json()
    b = chat(client, "c2", "capital of france").json()
    assert b["metadata"]["resolution_source"] == "LLM_CACHE" and b["reply"] == a["reply"]
    assert b["metadata"]["key_id"] is None and b["metadata"]["fallback_attempts"] == 0
    assert chat(client, "c3", "something else").json()["metadata"]["resolution_source"] == "LIVE_INFERENCE"


def test_real_failover(client):
    STATE["fail"] = {"k1"}
    m = chat(client, "f1", "x").json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1


def test_simulated_failover(client):
    r = chat(client, "f2", "y", **{"X-Simulate-Failure": "key_1=500"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"


def test_all_fail_503_not_stored(client):
    r = chat(client, "f3", "z", **{"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503 and r.json() == {"detail": "all providers unavailable"}
    assert client.get("/sessions/f3/messages").status_code == 404


@pytest.mark.parametrize("body", [{}, {"session_id": "", "message": "x"}, {"session_id": "s", "message": "   "},
                                  {"session_id": "s", "message": "a" * 4001}])
def test_422(client, body):
    assert client.post("/chat", json=body).status_code == 422


def test_malformed_json(client):
    r = client.post("/chat", content="{bad", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()


def test_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404 and r.json() == {"detail": "session not found"}
