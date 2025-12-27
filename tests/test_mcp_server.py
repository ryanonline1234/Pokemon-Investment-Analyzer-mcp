from fastapi.testclient import TestClient
from unittest.mock import patch, Mock
import pytest

from mcp import server


def test_health():
    client = TestClient(server.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@patch('analyzer.analyzer_core.compute_metrics')
def test_analyze_endpoint_no_ai(mock_compute):
    mock_compute.return_value = {"box_price": 42, "sold_count_30d": 5, "top_chase": {"sum_top": 100}}
    client = TestClient(server.app)
    r = client.post("/analyze", json={"set_name": "Test Set", "use_ai": False})
    assert r.status_code == 200
    data = r.json()
    assert "metrics" in data
    assert data["metrics"]["box_price"] == 42


@patch('analyzer.analyzer_core.compute_metrics')
@patch('mcp.adapter.AIAdapter.explain')
def test_analyze_endpoint_with_ai(mock_explain, mock_compute):
    mock_compute.return_value = {"box_price": 10, "sold_count_30d": 1, "top_chase": {"sum_top": 20}}
    mock_explain.return_value = "AI summary"
    client = TestClient(server.app)
    r = client.post("/analyze", json={"set_name": "Test Set", "use_ai": True})
    assert r.status_code == 200
    data = r.json()
    assert data.get("ai_explanation") == "AI summary"
