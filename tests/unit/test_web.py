"""The dashboard page must render (regression: Starlette 1.x dropped the
TemplateResponse(name, {"request": ...}) signature → HTTP 500 on '/')."""
from fastapi.testclient import TestClient

from web.app import app


def test_dashboard_page_renders():
    r = TestClient(app).get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
