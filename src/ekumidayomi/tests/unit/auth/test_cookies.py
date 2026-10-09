from fastapi import Response

from ekumidayomi.auth.dependencies import cookie_name, set_session_cookie
from ekumidayomi.core.settings import Settings


def test_cookie_is_host_only_secure_http_only() -> None:
    settings = Settings(secure_cookies=True)
    response = Response()
    set_session_cookie(response, "opaque-test-secret", settings, 300)
    value = response.headers["set-cookie"]
    assert cookie_name(settings).startswith("__Host-")
    assert "HttpOnly" in value and "Secure" in value and "SameSite=lax" in value
    assert "Path=/" in value and "Domain=" not in value
    assert response.headers["cache-control"] == "no-store"
