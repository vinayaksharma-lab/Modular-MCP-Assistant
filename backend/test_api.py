"""
Unit and Integration tests for FastAPI backend and MCP tools.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app


@pytest.mark.asyncio
async def test_health_endpoint():
    """Verify health endpoint returns status ok and discovered tools."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "get_current_time" in data["discovered_tools"]
        assert "query_database" in data["discovered_tools"]


@pytest.mark.asyncio
async def test_tools_endpoint():
    """Verify tools endpoint lists all MCP tools with schemas."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/tools")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 4
        tool_names = [t["name"] for t in data["tools"]]
        assert "get_current_time" in tool_names
        assert "calculate_math" in tool_names


@pytest.mark.asyncio
async def test_chat_endpoint_time_tool():
    """Verify chat endpoint executes time MCP tool on time query."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"message": "What is the current time in UTC?"}
        response = await client.post("/api/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert len(data["tool_calls"]) > 0
        assert data["tool_calls"][0]["tool_name"] == "get_current_time"


@pytest.mark.asyncio
async def test_chat_endpoint_math_tool():
    """Verify chat endpoint executes calculate_math MCP tool."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"message": "Calculate 150 * 4 + 25"}
        response = await client.post("/api/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert len(data["tool_calls"]) > 0
        assert data["tool_calls"][0]["tool_name"] == "calculate_math"


@pytest.mark.asyncio
async def test_chat_endpoint_db_tool():
    """Verify chat endpoint executes query_database MCP tool."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"message": "Show products in database with Quantum"}
        response = await client.post("/api/chat", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "reply" in data
        assert len(data["tool_calls"]) > 0
        assert data["tool_calls"][0]["tool_name"] == "query_database"


@pytest.mark.asyncio
async def test_chat_endpoint_empty_message():
    """Verify chat endpoint returns 422 or 400 on empty message."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {"message": ""}
        response = await client.post("/api/chat", json=payload)
        assert response.status_code in [400, 422]
