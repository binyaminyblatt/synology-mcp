"""Unit tests that exercise the client and tools against a mocked DSM API.

No real NAS is required — httpx.MockTransport answers the entry.cgi calls.
"""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from synology_mcp import api
from synology_mcp.app import check, ttl_cache


def _params(request: httpx.Request) -> dict:
    q = parse_qs(urlparse(str(request.url)).query)
    return {k: v[0] for k, v in q.items()}


def _ok(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": data})


def _err(code: int) -> httpx.Response:
    return httpx.Response(200, json={"success": False, "error": {"code": code}})


@pytest.fixture(autouse=True)
def reset_session():
    api._session_id = None
    api._client = None
    yield
    api._session_id = None
    api._client = None


def install_handler(handler):
    api._client = httpx.AsyncClient(
        base_url="http://nas:5000", transport=httpx.MockTransport(handler)
    )


# ── check() ──────────────────────────────────────────────────────────────────

def test_check_returns_data():
    assert check({"success": True, "data": {"x": 1}}) == {"x": 1}


def test_check_friendly_permission_error():
    with pytest.raises(RuntimeError, match="permission"):
        check({"success": False, "error": {"code": 105}})


def test_check_unknown_code_still_raises():
    with pytest.raises(RuntimeError, match="code 4242"):
        check({"success": False, "error": {"code": 4242}})


# ── login / call / re-auth ─────────────────────────────────────────────────────

async def test_login_and_call():
    def handler(request):
        p = _params(request)
        if p["api"] == "SYNO.API.Auth" and p["method"] == "login":
            return _ok({"sid": "SID123"})
        if p["api"] == "SYNO.DSM.Info":
            assert p["_sid"] == "SID123"
            return _ok({"model": "DS999", "version_string": "DSM 7.x"})
        return _err(102)

    install_handler(handler)
    r = await api.call("SYNO.DSM.Info", "getinfo", version=2)
    assert r["success"] and r["data"]["model"] == "DS999"


async def test_reauth_on_expired_session():
    state = {"logins": 0, "first": True}

    def handler(request):
        p = _params(request)
        if p["api"] == "SYNO.API.Auth" and p["method"] == "login":
            state["logins"] += 1
            return _ok({"sid": f"SID{state['logins']}"})
        if state["first"]:
            state["first"] = False
            return _err(119)  # expired session → triggers one re-auth + retry
        return _ok({"ok": True})

    install_handler(handler)
    r = await api.call("SYNO.Core.System", "info", version=1)
    assert r["success"] is True
    assert state["logins"] == 2  # initial login + re-auth


# ── ttl_cache ───────────────────────────────────────────────────────────────────

async def test_ttl_cache_caches_within_window():
    calls = {"n": 0}

    @ttl_cache(60)
    async def f():
        calls["n"] += 1
        return calls["n"]

    assert await f() == 1
    assert await f() == 1  # served from cache
    assert calls["n"] == 1


# ── a tool end-to-end (formatting) ─────────────────────────────────────────────

async def test_get_system_info_formats_fields():
    from synology_mcp.tools import monitoring

    def handler(request):
        p = _params(request)
        if p["api"] == "SYNO.API.Auth":
            return _ok({"sid": "S"})
        if p["api"] == "SYNO.DSM.Info":
            return _ok({"model": "DS423+", "version_string": "DSM 7.3.2",
                        "uptime": 90061, "ram": 10240, "temperature": 47})
        if p["api"] == "SYNO.Core.Network":
            return _ok({"server_name": "nas-test"})
        return _err(102)

    install_handler(handler)
    out = json.loads(await monitoring.get_system_info())
    assert out["model"] == "DS423+"
    assert out["hostname"] == "nas-test"
    assert out["uptime"] == "1d 1h 1m"
    assert out["temperature_c"] == 47


# ── Container Manager / Docker tools & annotations ────────────────────────────

async def test_container_manager_tools():
    from synology_mcp.tools import docker

    def handler(request):
        p = _params(request)
        if p["api"] == "SYNO.API.Auth":
            return _ok({"sid": "S", "synotoken": "TOK1"})
        if p["api"] == "SYNO.Docker.Container" and p["method"] == "get":
            assert p["name"] == "homeassistant"
            return _ok({
                "profile": {
                    "image": "ghcr.io/home-assistant/home-assistant:stable",
                    "env_variables": [{"key": "TZ", "value": "Asia/Jerusalem"}],
                    "port_bindings": [{"host_port": 8123, "container_port": 8123}],
                    "volume_bindings": [{"host_volume_file": "/docker/ha", "mount_point": "/config"}],
                    "use_host_network": True,
                },
                "details": {"status": "running", "up_time": 3600},
            })
        if p["api"] == "SYNO.Docker.Project" and p["method"] == "list":
            return _ok({
                "p1": {
                    "id": "proj-uuid-1",
                    "name": "media-stack",
                    "status": "RUNNING",
                    "share_path": "/docker/media-stack",
                    "containerIds": ["c1", "c2"],
                }
            })
        if p["api"] == "SYNO.Docker.Project" and p["method"] == "get":
            return _ok({
                "id": "proj-uuid-1",
                "name": "media-stack",
                "status": "RUNNING",
                "share_path": "/docker/media-stack",
                "content": "services:\n  sonarr:\n    image: lscr.io/linuxserver/sonarr:latest\n",
            })
        if p["api"] == "SYNO.Docker.Network" and p["method"] == "list":
            return _ok({
                "network": [
                    {"id": "net1234567890", "name": "bridge", "driver": "bridge", "subnet": "172.17.0.0/16"}
                ]
            })
        return _err(102)

    install_handler(handler)

    details = json.loads(await docker.get_container_details("homeassistant"))
    assert details["image"] == "ghcr.io/home-assistant/home-assistant:stable"
    assert details["use_host_network"] is True

    proj = json.loads(await docker.get_docker_project_details("media-stack"))
    assert proj["id"] == "proj-uuid-1"
    assert "sonarr:" in proj["compose_yaml"]

    nets = json.loads(await docker.list_docker_networks())
    assert nets["total"] == 1
    assert nets["networks"][0]["name"] == "bridge"


async def test_tool_annotations_populated():
    from synology_mcp.app import mcp

    tools = await mcp.list_tools()
    by_name = {t.name: t for t in tools}
    assert len(by_name) >= 90

    def _ro(t):
        return getattr(t.annotations, "read_only_hint", getattr(t.annotations, "readOnlyHint", None))

    def _dest(t):
        return getattr(t.annotations, "destructive_hint", getattr(t.annotations, "destructiveHint", None))

    # Read-only tools
    assert _ro(by_name["list_containers"]) is True
    assert _ro(by_name["get_container_details"]) is True
    assert _ro(by_name["get_docker_project_details"]) is True
    assert _ro(by_name["read_text_file"]) is True

    # Write tools (non-destructive)
    assert _ro(by_name["set_container_state"]) is False
    assert _ro(by_name["manage_docker_project"]) is False

    # Destructive tools
    assert _dest(by_name["delete_container"]) is True
    assert _dest(by_name["delete_docker_image"]) is True
    assert _dest(by_name["reboot_nas"]) is True
