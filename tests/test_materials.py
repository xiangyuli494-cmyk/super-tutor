"""Tests for material upload and status endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient


class TestMaterials:
    """Material API tests."""

    async def test_upload_text_material(self, client: TestClient):
        """POST /api/v1/materials/upload — should create a material."""
        resp = client.post("/api/v1/materials/upload", json={
            "title": "大学物理·力学篇",
            "content": "牛顿第一定律：物体在不受外力作用时，保持静止或匀速直线运动状态。\n牛顿第二定律：F=ma。\n牛顿第三定律：作用力与反作用力大小相等、方向相反。",
            "subject": "物理",
            "description": "牛顿三大定律基础材料",
        })
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert "material_id" in data["data"]
        assert data["data"]["title"] == "大学物理·力学篇"
        assert data["data"]["status"] != ""  # status field present

    async def test_get_material_status(self, client: TestClient):
        """GET /api/v1/materials/{id}/status — should return material info."""
        # Upload first
        upload_resp = client.post("/api/v1/materials/upload", json={
            "title": "测试材料",
            "content": "一些测试内容。",
            "subject": "数学",
        })
        material_id = upload_resp.json()["data"]["material_id"]

        # Query status
        resp = client.get(f"/api/v1/materials/{material_id}/status")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["material_id"] == material_id
        assert data["data"]["title"] == "测试材料"
        assert data["data"]["subject"] == "数学"
        # Newly uploaded material should be in "draft" status
        assert "status" in data["data"]

    async def test_upload_empty_title(self, client: TestClient):
        """POST /api/v1/materials/upload with empty title → 422."""
        resp = client.post("/api/v1/materials/upload", json={
            "title": "",
            "content": "内容",
        })
        assert resp.status_code == 422, resp.text

    async def test_get_nonexistent_material(self, client: TestClient):
        """GET /api/v1/materials/{id}/status with bad id → 404."""
        resp = client.get("/api/v1/materials/nonexistent-id/status")
        assert resp.status_code == 404, resp.text
