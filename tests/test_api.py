"""
API integration tests for Hunyuan3D-2 API server.
Run: python -m pytest tests/test_api.py -v -p no:warnings
"""

import pytest
from httpx import AsyncClient, ASGITransport
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def client():
    from api_server import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    @pytest.mark.anyio
    async def test_health_returns_200(self, client):
        response = await client.get("/api/health")
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_health_has_required_fields(self, client):
        response = await client.get("/api/health")
        data = response.json()
        assert "status" in data
        assert "gpu" in data
        assert "models_loaded" in data
        assert "generation_busy" in data


class TestModelStatusEndpoint:
    @pytest.mark.anyio
    async def test_model_status_returns_200(self, client):
        response = await client.get("/api/models/status")
        assert response.status_code == 200

    @pytest.mark.anyio
    async def test_model_status_has_families(self, client):
        response = await client.get("/api/models/status")
        data = response.json()
        assert "families" in data
        assert isinstance(data["families"], list)
        assert len(data["families"]) > 0


class TestGenerateShapeValidation:
    @pytest.mark.anyio
    async def test_generate_shape_requires_image(self, client):
        response = await client.post("/api/generate/shape", data={})
        assert response.status_code == 422


class TestTaskEndpoints:
    @pytest.mark.anyio
    async def test_nonexistent_task_returns_404(self, client):
        response = await client.get("/api/tasks/nonexistent-123")
        assert response.status_code == 404


class TestExportValidation:
    @pytest.mark.anyio
    async def test_export_missing_mesh_path_returns_404(self, client):
        response = await client.post("/api/export", json={
            "format": "glb",
            "mesh_path": "/nonexistent/path.glb",
        })
        assert response.status_code == 404


class TestPartsValidation:
    @pytest.mark.anyio
    async def test_segment_requires_mesh_path(self, client):
        response = await client.post("/api/parts/segment", json={})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_generate_parts_requires_internal_state(self, client):
        response = await client.post("/api/parts/generate", json={})
        assert response.status_code == 422

    @pytest.mark.anyio
    async def test_prepare_print_requires_internal_state(self, client):
        response = await client.post("/api/parts/print", json={})
        assert response.status_code == 422
