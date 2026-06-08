from __future__ import annotations

import httpx

from _helpers import response_json


def test_info(client: httpx.Client) -> None:
    response = client.get("/info")

    assert response.status_code == 200
    payload = response_json(response)
    assert isinstance(payload["version"], str)
    assert payload["description"] == "BiBLE-Atlas: Agent-native context DB"
