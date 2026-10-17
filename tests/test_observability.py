"""Homework 2 authentication checks; no model or tracing service required."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from server import app as server_app


@pytest.fixture
def client(world, tmp_path, monkeypatch):
    monkeypatch.setattr(server_app, "_SESSIONS", {})
    monkeypatch.setattr(server_app, "SESSIONS_DB", tmp_path / "sessions.db")
    # No lifespan startup: these tests do not initialize tracing exporters.
    return TestClient(server_app.app)


def test_session_rejects_claimed_role_mismatch(client):
    response = client.post("/sessions", json={"user_id": 1, "role": "support"})
    assert response.status_code == 403
    assert server_app._SESSIONS == {}


def test_token_cannot_authorize_another_session(client, monkeypatch):
    first = client.post("/sessions", json={"user_id": 1, "role": "shopper"})
    second = client.post("/sessions", json={"user_id": 9002, "role": "merchant"})
    assert first.status_code == second.status_code == 200
    first, second = first.json(), second.json()
    # Confirm the token works for its own session before trying another.
    auth = "Bearer " + first["token"]
    assert server_app._authorize(first["session_id"], auth).user_id == 1
    runner = AsyncMock(side_effect=AssertionError("Unauthorized request ran the agent"))
    monkeypatch.setattr(server_app.Runner, "run", runner)
    response = client.post(
        f"/sessions/{second['session_id']}/messages",
        headers={"Authorization": auth},
        json={"message": "Show my orders."},
    )
    assert response.status_code == 403
    runner.assert_not_awaited()
