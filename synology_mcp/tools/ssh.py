"""Local SSH tools using the configured DSM administrator credentials."""

from __future__ import annotations

import asyncio
import os
import shlex
from urllib.parse import urlparse

import asyncssh

from .. import api, config
from ..app import fmt, mcp

_MAX_OUTPUT_CHARS = 50000


async def _resolve_ssh_target() -> tuple[str, int]:
    host = os.getenv("SYNOLOGY_SSH_HOST", "").strip()
    if not host:
        host = urlparse(config.URL).hostname or "127.0.0.1"

    port_env = os.getenv("SYNOLOGY_SSH_PORT", "").strip()
    if port_env:
        return host, int(port_env)

    try:
        res = await api.call("SYNO.Core.Terminal", "get", version=3)
        if res.get("success"):
            port = res.get("data", {}).get("ssh_port")
            if port:
                return host, int(port)
    except Exception:
        pass
    return host, 22


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text, False
    return text[-_MAX_OUTPUT_CHARS:], True


async def _exec_ssh(command: str, sudo: bool = False, timeout: int = 30) -> dict:
    config.validate()
    host, port = await _resolve_ssh_target()

    run_cmd = command
    stdin_input: str | None = None
    if sudo:
        run_cmd = f"sudo -S -p '' sh -c {shlex.quote(command)}"
        stdin_input = f"{config.PASSWORD}\n"

    async with asyncssh.connect(
        host,
        port=port,
        username=config.USER,
        password=config.PASSWORD,
        known_hosts=None,
        connect_timeout=10,
    ) as conn:
        result = await asyncio.wait_for(
            conn.run(run_cmd, input=stdin_input, check=False),
            timeout=max(1, min(timeout, 300)),
        )

    stdout, stdout_trunc = _truncate(result.stdout or "")
    stderr, stderr_trunc = _truncate(result.stderr or "")
    return {
        "host": host,
        "port": port,
        "exit_status": result.exit_status,
        "stdout": stdout,
        "stderr": stderr,
        "truncated": stdout_trunc or stderr_trunc,
    }


@mcp.tool()
async def ssh_run_command(command: str, sudo: bool = False, timeout: int = 30) -> str:
    """
    Execute a shell command over local SSH using the configured DSM admin credentials. [control]

    Args:
        command: Shell command to execute on the NAS
        sudo: Run via ``sudo -S`` using the same password for root-only logs/commands
        timeout: Command timeout in seconds (1-300, default 30)
    """
    return fmt(await _exec_ssh(command, sudo=sudo, timeout=timeout))


@mcp.tool()
async def ssh_read_log(log_path: str, lines: int = 200, sudo: bool = False) -> str:
    """
    Read the tail of a system or service log file on the NAS over local SSH.

    Args:
        log_path: Absolute path to the log file (e.g. "/var/log/messages")
        lines: Number of trailing lines to return (1-2000, default 200)
        sudo: Run ``tail`` via ``sudo -S`` for root-owned logs (default False)
    """
    n = max(1, min(int(lines), 2000))
    cmd = f"tail -n {n} -- {shlex.quote(log_path)}"
    return fmt(await _exec_ssh(cmd, sudo=sudo, timeout=30))
