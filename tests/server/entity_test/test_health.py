from __future__ import annotations

import httpx


def test_health(client: httpx.Client) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
