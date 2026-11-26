"""Async client for the Synology DSM 7 Web API.

A thin wrapper around the ``entry.cgi`` gateway that handles login (including
2FA via a trusted-device token), session caching, file download/upload, and
automatic re-authentication when a session expires.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from . import config

# httpx logs full request URLs at INFO level, which would leak the password and
# session id into the server's stderr. Keep those loggers quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

_session_id: str | None = None
_syno_token: str | None = None
_client: httpx.AsyncClient | None = None

# Synology SYNO.API.Auth error codes → human-readable hints.
_AUTH_ERRORS = {
    400: "no such account or incorrect password",
    401: "account disabled",
    402: "permission denied",
    403: "2FA (OTP) code required — run the bootstrap script to get a device token",
    404: "failed to authenticate 2FA code",
    406: "2FA enforced — a one-time OTP code is required to bootstrap",
    407: "blocked IP source",
    408: "expired password (cannot change)",
    409: "expired password",
    410: "password must be changed",
}


def _default_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    if config.CF_ACCESS_CLIENT_ID and config.CF_ACCESS_CLIENT_SECRET:
        headers["CF-Access-Client-Id"] = config.CF_ACCESS_CLIENT_ID
        headers["CF-Access-Client-Secret"] = config.CF_ACCESS_CLIENT_SECRET
    return headers


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=config.URL,
            verify=config.VERIFY_SSL,
            timeout=config.TIMEOUT,
            headers=_default_headers(),
        )
    return _client


async def _login() -> str:
    global _syno_token
    params = {
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": config.USER,
        "passwd": config.PASSWORD,
        "session": config.SESSION_NAME,
        "format": "sid",
        "enable_syno_token": "yes",
    }
    # A trusted-device token avoids needing a fresh OTP on every login.
    if config.DEVICE_ID:
        params["device_id"] = config.DEVICE_ID
        params["device_name"] = config.DEVICE_NAME
    elif config.OTP_CODE:
        params["otp_code"] = config.OTP_CODE

    r = await _get_client().get("/webapi/entry.cgi", params=params)
    d = r.json()
    if not d.get("success"):
        code = d.get("error", {}).get("code", "?")
        hint = _AUTH_ERRORS.get(code, "unknown error")
        raise RuntimeError(f"Synology authentication failed (code {code}: {hint})")
    _syno_token = d["data"].get("synotoken")
    return d["data"]["sid"]


async def bootstrap_device_token(otp_code: str) -> str:
    """Exchange a one-time OTP code for a persistent trusted-device token.

    Returns the ``device_id`` to be stored as ``SYNOLOGY_DEVICE_ID`` so the
    server can log in without a fresh OTP each time.
    """
    r = await _get_client().get("/webapi/entry.cgi", params={
        "api": "SYNO.API.Auth",
        "version": "6",
        "method": "login",
        "account": config.USER,
        "passwd": config.PASSWORD,
        "session": config.SESSION_NAME,
        "format": "sid",
        "otp_code": otp_code,
        "enable_device_token": "yes",
        "device_name": config.DEVICE_NAME,
    })
    d = r.json()
    if not d.get("success"):
        code = d.get("error", {}).get("code", "?")
        hint = _AUTH_ERRORS.get(code, "unknown error")
        raise RuntimeError(f"Bootstrap failed (code {code}: {hint})")
    did = d["data"].get("did")
    if not did:
        raise RuntimeError(f"No device token returned by DSM: {d['data']}")
    return did


async def _ensure_session() -> str:
    global _session_id
    if _session_id is None:
        _session_id = await _login()
    return _session_id


async def call(api: str, method: str, version: int = 1, http_method: str = "GET", **kwargs) -> dict:
    """Call a Synology API method. Re-authenticates once on session expiry.

    Keyword arguments become request parameters; ``None`` values are dropped.
    """
    global _session_id

    sid = await _ensure_session()
    params: dict[str, Any] = {
        "api": api,
        "method": method,
        "version": str(version),
        "_sid": sid,
    }
    if _syno_token:
        params["SynoToken"] = _syno_token
    params.update({k: v for k, v in kwargs.items() if v is not None})

    client = _get_client()
    if http_method.upper() == "POST":
        r = await client.post(
            "/webapi/entry.cgi",
            params={"_sid": sid, **({"SynoToken": _syno_token} if _syno_token else {})},
            data=params,
        )
    else:
        r = await client.get("/webapi/entry.cgi", params=params)
    d = r.json()

    # 119 = session timed out / invalid sid → re-auth and retry once.
    if not d.get("success") and d.get("error", {}).get("code") in (106, 107, 119):
        _session_id = None
        sid = await _ensure_session()
        params["_sid"] = sid
        if _syno_token:
            params["SynoToken"] = _syno_token
        if http_method.upper() == "POST":
            r = await client.post(
                "/webapi/entry.cgi",
                params={"_sid": sid, **({"SynoToken": _syno_token} if _syno_token else {})},
                data=params,
            )
        else:
            r = await client.get("/webapi/entry.cgi", params=params)
        d = r.json()

    return d


async def download_raw(api: str, method: str, version: int = 1, **kwargs) -> bytes:
    """Call a Synology API method that returns raw file bytes (e.g. FileStation.Download)."""
    global _session_id

    sid = await _ensure_session()
    params: dict[str, Any] = {
        "api": api,
        "method": method,
        "version": str(version),
        "_sid": sid,
    }
    if _syno_token:
        params["SynoToken"] = _syno_token
    params.update({k: v for k, v in kwargs.items() if v is not None})

    r = await _get_client().get("/webapi/entry.cgi", params=params)
    content_type = r.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            d = r.json()
            if isinstance(d, dict) and d.get("success") is False:
                if d.get("error", {}).get("code") in (106, 107, 119):
                    _session_id = None
                    params["_sid"] = await _ensure_session()
                    if _syno_token:
                        params["SynoToken"] = _syno_token
                    r = await _get_client().get("/webapi/entry.cgi", params=params)
                    return r.content
                code = d.get("error", {}).get("code", "?")
                raise RuntimeError(f"Synology download failed (code {code})")
        except ValueError:
            pass
    return r.content


async def upload_file_bytes(
    folder_path: str,
    filename: str,
    content: bytes,
    overwrite: bool = True,
    create_parents: bool = True,
) -> dict:
    """Upload raw bytes as a file via ``SYNO.FileStation.Upload``."""
    global _session_id

    sid = await _ensure_session()
    query_params: dict[str, Any] = {
        "api": "SYNO.FileStation.Upload",
        "method": "upload",
        "version": "2",
        "_sid": sid,
    }
    if _syno_token:
        query_params["SynoToken"] = _syno_token

    data = {
        "path": folder_path,
        "create_parents": "true" if create_parents else "false",
        "overwrite": "true" if overwrite else "false",
    }
    files = {"file": (filename, content, "application/octet-stream")}
    r = await _get_client().post("/webapi/entry.cgi", params=query_params, data=data, files=files)
    d = r.json()
    if not d.get("success") and d.get("error", {}).get("code") in (106, 107, 119):
        _session_id = None
        query_params["_sid"] = await _ensure_session()
        if _syno_token:
            query_params["SynoToken"] = _syno_token
        r = await _get_client().post("/webapi/entry.cgi", params=query_params, data=data, files=files)
        d = r.json()
    return d


async def wait_for_task(api: str, taskid: str, max_wait: int = 60) -> dict:
    """Poll a long-running Synology task until it reports finished or times out."""
    for _ in range(max_wait * 2):
        result = await call(api, "status", taskid=taskid)
        if result.get("success") and result.get("data", {}).get("finished"):
            return result
        await asyncio.sleep(0.5)
    return {"success": False, "error": {"msg": "Task timed out"}}


async def close() -> None:
    """Close the shared HTTP client (used by tests / scripts)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
