import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from rif_runtime.api import app
from rif_runtime.auth import ENV_VAR, READ_AUTH_ENV_VAR

client = TestClient(app)

GUARDED_REQUESTS = [
    ("post", "/v1/environment/default"),
    ("post", "/v1/posture/normal"),
    ("post", "/v1/posture/reset"),
    (
        "post",
        "/v1/mcp/metasploit/token",
        {"intent": {"capability": "module.search", "target": "10.10.10.5"}},
    ),
    (
        "post",
        "/v1/policy/evaluate",
        {"actor": "agent:test", "action": "read", "target": "resource"},
    ),
]


def _call(method, path, json=None, headers=None):
    return getattr(client, method)(path, json=json, headers=headers)


def test_guarded_endpoints_reject_when_no_keys_configured(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    for method, path, *rest in GUARDED_REQUESTS:
        body = rest[0] if rest else None
        response = _call(method, path, json=body)
        assert response.status_code == 503, f"{method} {path} did not fail closed"


def test_guarded_endpoints_reject_missing_or_wrong_key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "correct-key")
    for method, path, *rest in GUARDED_REQUESTS:
        body = rest[0] if rest else None
        no_key = _call(method, path, json=body)
        assert no_key.status_code == 401

        wrong_key = _call(method, path, json=body, headers={"X-API-Key": "wrong-key"})
        assert wrong_key.status_code == 401


def test_guarded_endpoints_accept_valid_key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "correct-key")
    headers = {"X-API-Key": "correct-key"}

    response = _call("post", "/v1/environment/default", headers=headers)
    assert response.status_code != 401

    response = _call("post", "/v1/posture/normal", headers=headers)
    assert response.status_code != 401

    response = _call("post", "/v1/posture/reset", headers=headers)
    assert response.status_code != 401

    response = _call(
        "post",
        "/v1/mcp/metasploit/token",
        json={"intent": {"capability": "module.search", "target": "10.10.10.5"}},
        headers=headers,
    )
    assert response.status_code != 401

    response = _call(
        "post",
        "/v1/policy/evaluate",
        json={"actor": "agent:test", "action": "read", "target": "resource"},
        headers=headers,
    )
    assert response.status_code != 401


def test_policy_crud_requires_key(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "correct-key")
    headers = {"X-API-Key": "correct-key"}
    rule = {"id": "test-rule", "effect": "allow", "action": "*", "target": "*"}

    unauthenticated = client.put("/v1/policies/test-rule", json=rule)
    assert unauthenticated.status_code == 401

    authenticated = client.put("/v1/policies/test-rule", json=rule, headers=headers)
    assert authenticated.status_code != 401

    delete_unauth = client.delete("/v1/policies/test-rule")
    assert delete_unauth.status_code == 401

    delete_auth = client.delete("/v1/policies/test-rule", headers=headers)
    assert delete_auth.status_code != 401


def test_read_only_endpoints_stay_open(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert client.get("/health").status_code == 200
    assert client.get("/v1/environments").status_code == 200
    assert client.get("/v1/policies").status_code == 200


def test_api_key_length_mismatch_returns_401_not_500(monkeypatch):
    """Cursor Bugbot finding: a key shorter/longer than any configured key
    must not raise ValueError inside hmac.compare_digest -- it should fall
    through to a clean 401."""
    monkeypatch.setenv(ENV_VAR, "a-much-longer-configured-key-value")
    headers = {"X-API-Key": "short"}
    response = _call("post", "/v1/posture/normal", headers=headers)
    assert response.status_code == 401


# --- read-scope auth ---------------------------------------------------------

READ_GUARDED_PATHS = [
    "/v1/audit",
    "/v1/policies",
    "/v1/recovered-state",
    "/v1/persistence/summary",
    "/v1/telemetry/summary",
    "/v1/graph/summary",
]


def test_read_endpoints_are_open_by_default(monkeypatch):
    """The flag is opt-in, so an upgrade does not break existing readers."""
    monkeypatch.delenv(READ_AUTH_ENV_VAR, raising=False)
    monkeypatch.delenv(ENV_VAR, raising=False)

    for path in READ_GUARDED_PATHS:
        assert client.get(path).status_code == 200, path


def test_read_endpoints_reject_missing_or_wrong_key_when_enabled(monkeypatch):
    monkeypatch.setenv(READ_AUTH_ENV_VAR, "true")
    monkeypatch.setenv(ENV_VAR, "correct-key")

    for path in READ_GUARDED_PATHS:
        assert client.get(path).status_code == 401, path
        wrong = client.get(path, headers={"X-API-Key": "wrong-key"})
        assert wrong.status_code == 401, path


def test_read_endpoints_accept_valid_key_when_enabled(monkeypatch):
    monkeypatch.setenv(READ_AUTH_ENV_VAR, "true")
    monkeypatch.setenv(ENV_VAR, "correct-key")

    for path in READ_GUARDED_PATHS:
        response = client.get(path, headers={"X-API-Key": "correct-key"})
        assert response.status_code == 200, path


def test_read_endpoints_fail_closed_when_enabled_without_keys(monkeypatch):
    """Enabling the guard with no keys configured must not silently open it."""
    monkeypatch.setenv(READ_AUTH_ENV_VAR, "true")
    monkeypatch.delenv(ENV_VAR, raising=False)

    for path in READ_GUARDED_PATHS:
        assert client.get(path).status_code == 503, path


def test_health_stays_open_when_read_auth_is_enabled(monkeypatch):
    """Liveness probes must not need a credential."""
    monkeypatch.setenv(READ_AUTH_ENV_VAR, "true")
    monkeypatch.setenv(ENV_VAR, "correct-key")

    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200


# --- route inventory ---------------------------------------------------------
#
# The fix above is a one-off; this test is what keeps the surface honest. A new
# route added without a guard fails here rather than shipping unnoticed.

PUBLIC_ROUTES = {
    # Liveness and service discovery: no governance state in either response.
    ("GET", "/health"),
    ("GET", "/"),
    # Environment *names* and their profiles, not decisions. Listed public
    # deliberately; move it to a guard if profiles ever carry secrets.
    ("GET", "/v1/environments"),
    # Static capability metadata for the Metasploit surface.
    ("GET", "/v1/mcp/metasploit/capabilities"),
    # Dry-run simulation routes: runtime.evaluate(record=False), so they
    # cannot mutate posture or append to the stores. See api.py.
    ("POST", "/v1/mcp/invoke"),
    ("POST", "/v1/mcp/metasploit/evaluate"),
    # Guarded by a Supabase bearer JWT (_require_identity), not X-API-Key.
    ("POST", "/v1/runs"),
    # FastAPI's own docs endpoints.
    ("GET", "/openapi.json"),
    ("GET", "/docs"),
    ("GET", "/docs/oauth2-redirect"),
    ("GET", "/redoc"),
}


def _declared_routes():
    from rif_runtime.api import app as api_app

    seen = set()
    for route in api_app.routes:
        methods = getattr(route, "methods", None) or {"GET"}
        for method in methods:
            if method in ("HEAD", "OPTIONS"):
                continue
            seen.add((method, route.path))
    return seen


def _guarded_routes():
    from fastapi.routing import APIRoute

    from rif_runtime.api import app as api_app
    from rif_runtime.auth import require_api_key, require_read_api_key

    guards = {require_api_key, require_read_api_key}
    seen = set()
    for route in api_app.routes:
        if not isinstance(route, APIRoute):
            continue
        calls = {d.call for d in route.dependant.dependencies}
        if calls & guards:
            for method in route.methods:
                seen.add((method, route.path))
    return seen


def test_every_route_is_guarded_or_explicitly_public():
    """No route may be unguarded without being named in PUBLIC_ROUTES.

    Adding a route to that set is a deliberate act with a written reason; the
    failure message exists so the choice is made on purpose, not by omission.
    """
    unguarded = _declared_routes() - _guarded_routes() - PUBLIC_ROUTES

    assert not unguarded, (
        "unguarded route(s) not declared public: "
        f"{sorted(unguarded)}. Add a guard, or add an entry to PUBLIC_ROUTES "
        "with a comment explaining why the route discloses nothing sensitive."
    )


def test_public_route_allowlist_has_no_stale_entries():
    """A removed or renamed route must not linger in the allowlist."""
    stale = PUBLIC_ROUTES - _declared_routes()

    assert not stale, (
        f"PUBLIC_ROUTES lists route(s) that no longer exist: {sorted(stale)}"
    )


def test_a_non_ascii_configured_key_does_not_break_the_guard(monkeypatch):
    """The configured side is arbitrary operator text.

    hmac.compare_digest raises TypeError on a `str` holding non-ASCII
    characters, so the comparison operates on UTF-8 bytes. Comparing str would
    turn every request into a 500 for an operator whose key is not ASCII.
    (The presented side cannot carry non-ASCII at all -- HTTP header values are
    ASCII, and the client rejects it before the guard is reached.)
    """
    monkeypatch.setenv(ENV_VAR, "clé-de-contrôle")
    response = _call("post", "/v1/posture/normal", headers={"X-API-Key": "guess"})
    assert response.status_code == 401


def test_a_non_ascii_candidate_reaches_the_guard_without_raising():
    """Same property at the unit boundary, where HTTP encoding cannot mask it."""
    import os

    from rif_runtime.auth import require_api_key

    os.environ[ENV_VAR] = "clé-de-contrôle"
    try:
        with pytest.raises(HTTPException) as rejected:
            require_api_key("kéy")
        assert rejected.value.status_code == 401
        assert require_api_key("clé-de-contrôle") == "clé-de-contrôle"
    finally:
        del os.environ[ENV_VAR]


def test_api_keys_are_not_run_through_a_fast_hash(monkeypatch):
    """Pins the fix for CodeQL py/weak-sensitive-data-hashing (high).

    RIF_CONTROL_PLANE_API_KEYS flowed into hashlib.sha256, which reads as
    password hashing with a fast hash. The digest was there to equalise
    comparison lengths, on the mistaken premise that compare_digest raises on a
    length mismatch -- it does not. Comparing the secrets directly is what
    compare_digest is for, and it keeps the flow from existing at all.
    """
    import ast
    import inspect

    from rif_runtime import auth

    tree = ast.parse(inspect.getsource(auth))
    hashing = {"hashlib", "md5", "sha1", "sha256", "sha512", "blake2b"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.split(".")[0] for alias in node.names}
            assert not (names & hashing), f"auth.py imports {names & hashing}"
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            names = {alias.name for alias in node.names}
            assert module not in hashing, f"auth.py imports from {module}"
            assert not (names & hashing), f"auth.py imports {names & hashing}"
