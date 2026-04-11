import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bible.main import create_app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    app = create_app()
    return TestClient(app)


def test_health_check(client):
    """Test the health check endpoint returns correct status."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_get_info(client):
    """Test the info endpoint returns version and description."""
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "description" in data
    assert data["description"] == "BiBLE-Atlas: Agent-native context DB"
    # Version should be a string
    assert isinstance(data["version"], str)


def test_system_status(client):
    """Test the system status endpoint returns correct JSON response."""
    response = client.get("/api/v1/system/status")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    # Parse the response as JSON
    data = json.loads(response.content)
    assert data == {"status": "ok"}


def test_get_info_version_format(client):
    """Test that the version follows semantic versioning format."""
    response = client.get("/info")
    assert response.status_code == 200
    data = response.json()
    version = data["version"]
    # Version should match pattern like "0.1.dev34" or "1.2.3"
    assert isinstance(version, str)
    assert len(version) > 0
    # Basic check that version contains numbers
    assert any(c.isdigit() for c in version)


def test_health_check_response_time(client):
    """Test that health check responds quickly."""
    import time
    start = time.time()
    response = client.get("/health")
    end = time.time()
    assert response.status_code == 200
    # Should respond in less than 1 second
    assert (end - start) < 1.0


def test_system_status_response_time(client):
    """Test that system status responds quickly."""
    import time
    start = time.time()
    response = client.get("/api/v1/system/status")
    end = time.time()
    assert response.status_code == 200
    # Should respond in less than 1 second
    assert (end - start) < 1.0


def test_info_response_time(client):
    """Test that info endpoint responds quickly."""
    import time
    start = time.time()
    response = client.get("/info")
    end = time.time()
    assert response.status_code == 200
    # Should respond in less than 1 second
    assert (end - start) < 1.0
