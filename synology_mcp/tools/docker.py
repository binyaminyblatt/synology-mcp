"""Docker / Container Manager tools for Synology DSM 7.

Comprehensive coverage of Synology Container Manager (``SYNO.Docker.*``):
- Containers: list, inspect full profile (env, mounts, ports, networks, restart policy),
  logs, live CPU/RAM/network/disk stats, start/stop/restart, delete, prune stopped
- Compose Projects: list projects, get project details & docker-compose.yml content,
  start/stop/restart/build/clean project, create project from compose YAML
- Images & Registries: list images (with update status), pull image, upgrade image,
  delete image, prune unused images, search Docker Hub / registries, list registries
- Networks: list Docker networks, inspect network, create/delete network
"""

from __future__ import annotations

import json

from .. import api
from ..app import check, fmt, mcp, ts

# ── Containers ────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_containers(running_only: bool = False) -> str:
    """
    List all Docker / Container Manager containers with their state, image, ports and resource status.

    Args:
        running_only: If True, only return currently running containers (default False)
    """
    data = check(await api.call("SYNO.Docker.Container", "list", version=1, limit=-1, offset=0))
    containers = []
    for c in data.get("containers", []):
        state = c.get("state") or {}
        running = c.get("status") == "running" or state.get("Running", False)
        if running_only and not running:
            continue
        containers.append({
            "name": c.get("name"),
            "id": (c.get("id") or "")[:12] or None,
            "image": c.get("image"),
            "running": running,
            "state": state.get("Status") or c.get("status"),
            "up_status": c.get("up_status"),
            "exit_code": state.get("ExitCode"),
            "started_at": state.get("StartedAt"),
            "finished_at": state.get("FinishedAt"),
            "enable_restart_policy": c.get("enable_restart_policy"),
            "is_package": c.get("is_package"),
        })
    containers.sort(key=lambda x: (not x["running"], (x["name"] or "").lower()))
    running_cnt = sum(1 for c in containers if c["running"])
    return fmt({"total": len(containers), "running": running_cnt, "containers": containers})


@mcp.tool()
async def get_container_details(name: str) -> str:
    """
    Inspect a Docker container's full configuration profile (env vars, volume mounts,
    port bindings, network attachments, command/entrypoint, limits, and state).

    Args:
        name: Container name (from list_containers)
    """
    data = check(await api.call("SYNO.Docker.Container", "get", version=1, name=name))
    profile = data.get("profile") or {}
    details = data.get("details") or {}
    return fmt({
        "name": name,
        "image": profile.get("image") or data.get("image"),
        "status": details.get("status") or data.get("status"),
        "up_time": details.get("up_time"),
        "cmd": profile.get("cmd"),
        "entrypoint": profile.get("entrypoint"),
        "env_variables": profile.get("env_variables", []),
        "port_bindings": profile.get("port_bindings", []),
        "volume_bindings": profile.get("volume_bindings", []),
        "links": profile.get("links", []),
        "network": profile.get("network", []),
        "use_host_network": profile.get("use_host_network"),
        "privileged": profile.get("privileged"),
        "enable_restart_policy": profile.get("enable_restart_policy"),
        "cpu_priority": profile.get("cpu_priority"),
        "memory_limit_bytes": profile.get("memory_limit"),
        "raw_profile": profile,
    })


@mcp.tool()
async def get_container_logs(
    name: str,
    lines: int = 100,
    level: str | None = None,
    keyword: str | None = None,
) -> str:
    """
    Get recent log lines for a Docker container, with optional stream/keyword filtering.

    Args:
        name: Container name (from list_containers)
        lines: Number of recent log lines to return (default 100, max 1000)
        level: Optional stream filter — "stdout" or "stderr"
        keyword: Optional case-insensitive substring filter
    """
    lines = max(1, min(1000, lines))
    kwargs: dict = {
        "name": name,
        "sort_by": "time",
        "sort_dir": "DESC",
        "offset": 0,
        "limit": lines,
    }
    if level:
        kwargs["level"] = level
    if keyword:
        kwargs[" target"] = keyword
    data = check(await api.call("SYNO.Docker.Container.Log", "get", version=1, **kwargs))
    raw_logs = data.get("logs", data.get("items", []))
    entries = []
    for e in raw_logs:
        text = e.get("text", "")
        stream = e.get("stream") or e.get("level")
        if level and stream and stream.lower() != level.lower():
            continue
        if keyword and keyword.lower() not in (text or "").lower():
            continue
        entries.append({
            "time": ts(e.get("created")) or e.get("created"),
            "stream": stream,
            "text": text,
        })
    return fmt({"container": name, "lines": len(entries), "logs": entries})


@mcp.tool()
async def get_container_stats(name: str | None = None) -> str:
    """
    Get live CPU, memory, network and disk I/O resource usage for one container or all running containers.

    Args:
        name: Optional container name. If omitted, returns live resource stats for all running containers.
    """
    if name:
        data = check(await api.call("SYNO.Docker.Container.Resource", "get", version=1, name=name))
        res = data.get("resources", data)
        if isinstance(res, list):
            res = res[-1] if res else {}
        return fmt({
            "container": name,
            "cpu_pct": res.get("cpu") or res.get("cpu_percent"),
            "memory_mb": round((res.get("memory") or res.get("mem") or 0) / 1024 ** 2, 1)
            if (res.get("memory") or res.get("mem"))
            else None,
            "memory_pct": res.get("memory_percent"),
            "rx_bytes": res.get("rx"),
            "tx_bytes": res.get("tx"),
            "read_bytes": res.get("read"),
            "write_bytes": res.get("write"),
            "raw": res,
        })

    data = check(await api.call("SYNO.Docker.Container.Resource", "get", version=1))
    resources = data.get("resources", [])
    summary = []
    for r in resources if isinstance(resources, list) else []:
        mem = r.get("memory") or r.get("mem") or 0
        summary.append({
            "container": r.get("name"),
            "cpu_pct": r.get("cpu") or r.get("cpu_percent"),
            "memory_mb": round(mem / 1024 ** 2, 1) if mem else 0,
            "memory_pct": r.get("memory_percent"),
            "rx_bytes": r.get("rx"),
            "tx_bytes": r.get("tx"),
        })
    summary.sort(key=lambda x: (x.get("cpu_pct") or 0), reverse=True)
    return fmt({"total": len(summary), "containers": summary})


@mcp.tool()
async def set_container_state(name: str, action: str) -> str:
    """
    Start, stop, restart or force-stop (kill) a Docker container. [control]

    Args:
        name: Container name (from list_containers)
        action: "start", "stop", "restart" or "kill"
    """
    if action not in ("start", "stop", "restart", "kill"):
        raise ValueError("action must be 'start', 'stop', 'restart' or 'kill'")
    method = "force_stop" if action == "kill" else action
    check(await api.call("SYNO.Docker.Container", method, version=1, name=name))
    return fmt({"container": name, "action": action, "ok": True})


@mcp.tool()
async def delete_container(name: str, preserve_profile: bool = False) -> str:
    """
    Delete a stopped Docker container. [control]

    Args:
        name: Container name to delete
        preserve_profile: Keep container settings profile in DSM (default False)
    """
    check(await api.call(
        "SYNO.Docker.Container", "delete", version=1,
        name=name, is_preserve_profile="true" if preserve_profile else "false",
    ))
    return fmt({"container": name, "deleted": True})


@mcp.tool()
async def prune_stopped_containers() -> str:
    """Remove all stopped Docker containers (Container Manager 'Clean' containers). [control]"""
    data = check(await api.call("SYNO.Docker.Container", "prune", version=1))
    return fmt({"pruned_containers": True, "detail": data})


# ── Compose Projects (Container Manager Projects) ─────────────────────────────


@mcp.tool()
async def list_docker_projects() -> str:
    """List all Docker Compose / Container Manager projects with status, path and service counts."""
    data = check(await api.call("SYNO.Docker.Project", "list", version=1))
    projects = []
    items = data.values() if isinstance(data, dict) else data
    for p in items:
        if not isinstance(p, dict):
            continue
        projects.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "status": p.get("status"),
            "state": p.get("state"),
            "path": p.get("share_path") or p.get("path"),
            "containers": len(p.get("containerIds", []) or []),
            "container_ids": p.get("containerIds", []),
            "enable_service_portal": p.get("enable_service_portal"),
            "service_portal_port": p.get("service_portal_port"),
            "created": ts(p.get("created_at")) or p.get("created_at"),
            "updated": ts(p.get("updated_at")) or p.get("updated_at"),
        })
    projects.sort(key=lambda x: (x.get("status") != "RUNNING", (x.get("name") or "").lower()))
    return fmt({"total": len(projects), "projects": projects})


async def _resolve_project_id(id_or_name: str) -> tuple[str, dict]:
    """Resolve either a project UUID/id or human-readable project name to ``(id, project_dict)``."""
    data = check(await api.call("SYNO.Docker.Project", "list", version=1))
    items = data.values() if isinstance(data, dict) else data
    needle = id_or_name.strip().lower()
    for p in items:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        pname = str(p.get("name") or "")
        if pid.lower() == needle or pname.lower() == needle:
            return pid, p
    raise RuntimeError(f"Container Manager project '{id_or_name}' not found")


@mcp.tool()
async def get_docker_project_details(project: str) -> str:
    """
    Get full details for a Container Manager Compose project, including its ``docker-compose.yml``
    content, path, containers and status.

    Args:
        project: Project name or project ID (from list_docker_projects)
    """
    pid, summary = await _resolve_project_id(project)
    res = await api.call("SYNO.Docker.Project", "get", version=1, id=json.dumps(pid))
    detail = res.get("data", {}) if res.get("success") else summary

    # If compose YAML is not inline in detail, also try reading compose.yaml / docker-compose.yml from share_path
    yaml_content = detail.get("content") or summary.get("content")
    share_path = detail.get("share_path") or summary.get("share_path") or detail.get("path")
    if not yaml_content and share_path:
        for candidate in ("compose.yaml", "docker-compose.yml", "docker-compose.yaml", "compose.yml"):
            full_path = f"{share_path.rstrip('/')}/{candidate}"
            try:
                raw = await api.download_raw(
                    "SYNO.FileStation.Download", "download", version=2,
                    path=json.dumps([full_path]), mode='"open"',
                )
                text = raw.decode("utf-8", errors="replace")
                if "services:" in text or "version:" in text:
                    yaml_content = text
                    break
            except Exception:
                continue

    return fmt({
        "id": pid,
        "name": detail.get("name") or summary.get("name"),
        "status": detail.get("status") or summary.get("status"),
        "share_path": share_path,
        "containers": detail.get("containers") or summary.get("containerIds"),
        "compose_yaml": yaml_content,
        "raw": detail,
    })


@mcp.tool()
async def manage_docker_project(project: str, action: str) -> str:
    """
    Start, stop, restart, build (up --build / pull) or clean (down) a Container Manager Compose project. [control]

    Args:
        project: Project name or project ID (from list_docker_projects)
        action: One of "start", "stop", "restart", "build", "clean"
    """
    valid = {
        "start": ("SYNO.Docker.Project", "start"),
        "stop": ("SYNO.Docker.Project", "stop"),
        "restart": ("SYNO.Docker.Project", "restart"),
        "build": ("SYNO.Docker.Project", "build_stream"),
        "clean": ("SYNO.Docker.Project", "clean_stream"),
    }
    action = action.strip().lower()
    if action not in valid:
        raise ValueError(f"action must be one of: {', '.join(valid)}")

    pid, summary = await _resolve_project_id(project)
    api_name, method = valid[action]
    res = await api.call(api_name, method, version=1, id=json.dumps(pid))
    if not res.get("success") and method.endswith("_stream"):
        # Fallback to non-stream method name if supported on older DSM builds
        alt_method = method.replace("_stream", "")
        res = await api.call(api_name, alt_method, version=1, id=json.dumps(pid))
    data = check(res)
    return fmt({
        "project": summary.get("name") or pid,
        "id": pid,
        "action": action,
        "ok": True,
        "detail": data,
    })


@mcp.tool()
async def update_docker_project_compose(
    project: str,
    compose_yaml: str,
    rebuild: bool = False,
) -> str:
    """
    Update the ``docker-compose.yml`` content of an existing Container Manager project
    and optionally rebuild/restart it. [control]

    Args:
        project: Project name or project ID (from list_docker_projects)
        compose_yaml: Full YAML content for the project's docker-compose file
        rebuild: If True, also triggers a project build/restart after updating the YAML (default False)
    """
    pid, summary = await _resolve_project_id(project)
    res = await api.call(
        "SYNO.Docker.Project",
        "update",
        version=1,
        http_method="POST",
        id=json.dumps(pid),
        content=json.dumps(compose_yaml),
    )
    data = check(res)
    build_res = None
    if rebuild:
        b = await api.call("SYNO.Docker.Project", "build_stream", version=1, id=json.dumps(pid))
        build_res = b.get("data") if b.get("success") else b
    return fmt({
        "project": summary.get("name") or pid,
        "id": pid,
        "updated": True,
        "rebuilt": rebuild,
        "detail": data,
        "build_detail": build_res,
    })


# ── Images & Registries ───────────────────────────────────────────────────────


@mcp.tool()
async def list_docker_images(upgradable_only: bool = False) -> str:
    """
    List Docker images stored on the NAS, including size, tags and whether an update is available.

    Args:
        upgradable_only: If True, only return images that have a newer version available (default False)
    """
    data = check(await api.call("SYNO.Docker.Image", "list", version=1, limit=-1, offset=0))
    images = []
    for img in data.get("images", []):
        if upgradable_only and not img.get("upgradable"):
            continue
        size = int(img.get("size", 0) or 0)
        images.append({
            "repository": img.get("repository"),
            "tags": img.get("tags"),
            "id": (img.get("id") or "")[:12] or None,
            "size_mb": round(size / 1024 ** 2, 1) if size else None,
            "created": ts(img.get("created")) or img.get("created"),
            "upgradable": img.get("upgradable"),
        })
    images.sort(key=lambda x: (not bool(x.get("upgradable")), (x.get("repository") or "").lower()))
    return fmt({
        "total": len(images),
        "upgradable_count": sum(1 for i in images if i.get("upgradable")),
        "images": images,
    })


@mcp.tool()
async def pull_docker_image(repository: str, tag: str = "latest") -> str:
    """
    Pull (download) a Docker image from the configured registry into Container Manager. [control]

    Args:
        repository: Image repository name, e.g. "homeassistant/home-assistant" or "nginx"
        tag: Image tag (default "latest")
    """
    start = check(await api.call(
        "SYNO.Docker.Image", "pull_start", version=1,
        repository=repository, tag=tag,
    ))
    return fmt({
        "repository": repository,
        "tag": tag,
        "action": "pull_started",
        "task_id": start.get("task_id"),
        "detail": start,
    })


@mcp.tool()
async def upgrade_docker_image(repository: str, tag: str = "latest") -> str:
    """
    Upgrade an existing Docker image in Container Manager to the latest registry build. [control]

    Args:
        repository: Image repository name (from list_docker_images)
        tag: Image tag to upgrade (default "latest")
    """
    start = check(await api.call(
        "SYNO.Docker.Image", "upgrade_start", version=1,
        repository=repository, tag=tag,
    ))
    return fmt({
        "repository": repository,
        "tag": tag,
        "action": "upgrade_started",
        "task_id": start.get("task_id"),
        "detail": start,
    })


@mcp.tool()
async def delete_docker_image(repository: str, tag: str = "latest") -> str:
    """
    Delete a Docker image from Container Manager. [control]

    Args:
        repository: Image repository name (from list_docker_images)
        tag: Image tag to delete (default "latest")
    """
    objects = json.dumps([{"repository": repository, "tag": tag}])
    data = check(await api.call("SYNO.Docker.Image", "delete", version=1, objects=objects))
    return fmt({"repository": repository, "tag": tag, "deleted": True, "detail": data})


@mcp.tool()
async def prune_unused_docker_images() -> str:
    """Delete all unused / dangling Docker images in Container Manager to reclaim disk space. [control]"""
    data = check(await api.call("SYNO.Docker.Image", "prune", version=1))
    return fmt({"pruned_images": True, "detail": data})


@mcp.tool()
async def list_docker_registries() -> str:
    """List configured Docker image registries in Container Manager (Docker Hub, GHCR, custom)."""
    data = check(await api.call("SYNO.Docker.Registry", "get", version=1))
    return fmt(data)


# ── Networks ──────────────────────────────────────────────────────────────────


@mcp.tool()
async def list_docker_networks() -> str:
    """List all Docker networks in Container Manager with driver, subnet, gateway and connected containers."""
    data = check(await api.call("SYNO.Docker.Network", "list", version=1))
    networks = []
    for n in data.get("network", data.get("networks", [])):
        networks.append({
            "id": (n.get("id") or "")[:12] or None,
            "name": n.get("name"),
            "driver": n.get("driver"),
            "subnet": n.get("subnet"),
            "gateway": n.get("gateway"),
            "ip_range": n.get("ip_range"),
            "enable_ipv6": n.get("enable_ipv6"),
            "containers": n.get("containers", []),
            "disabled": n.get("disabled"),
        })
    return fmt({"total": len(networks), "networks": networks})


@mcp.tool()
async def create_docker_network(
    name: str,
    driver: str = "bridge",
    subnet: str | None = None,
    gateway: str | None = None,
) -> str:
    """
    Create a new Docker network in Container Manager. [control]

    Args:
        name: Network name
        driver: Network driver, e.g. "bridge" or "macvlan" (default "bridge")
        subnet: Optional CIDR subnet, e.g. "172.25.0.0/16"
        gateway: Optional gateway IP, e.g. "172.25.0.1"
    """
    kwargs: dict = {"name": name, "driver": driver}
    if subnet:
        kwargs["subnet"] = subnet
    if gateway:
        kwargs["gateway"] = gateway
    data = check(await api.call("SYNO.Docker.Network", "create", version=1, **kwargs))
    return fmt({"created": name, "driver": driver, "detail": data})


@mcp.tool()
async def delete_docker_network(name: str) -> str:
    """
    Delete a Docker network from Container Manager. [control]

    Args:
        name: Network name to delete
    """
    data = check(await api.call("SYNO.Docker.Network", "delete", version=1, names=json.dumps([name])))
    return fmt({"deleted": name, "detail": data})
