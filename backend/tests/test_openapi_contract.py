from pathlib import Path

import yaml

from app.main import app

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_committed_openapi_matches_application_schema():
    committed = yaml.safe_load((BACKEND_DIR / "openapi.yml").read_text(encoding="utf-8"))

    assert committed == app.openapi()


def test_openapi_declares_cookie_auth_and_sprint_two_paths():
    schema = app.openapi()

    assert schema["components"]["securitySchemes"]["SessionCookie"] == {
        "type": "apiKey",
        "description": "登录成功后由服务端设置的 HttpOnly 会话 Cookie。",
        "in": "cookie",
        "name": "healthos_session",
    }
    for path in (
        "/api/profile",
        "/api/profile/kcal-reference",
        "/api/meals",
        "/api/exercises",
        "/api/sleeps",
    ):
        assert path in schema["paths"]
