"""Active Backup for Business & Cloud Sync tools."""

from __future__ import annotations

from .. import api
from ..app import check, fmt, mcp, ts


@mcp.tool()
async def list_active_backup_tasks() -> str:
    """List Active Backup for Business tasks (PC, Server, VM, File Server)."""
    data = check(await api.call("SYNO.ActiveBackup.Task", "list", version=1))
    tasks = []
    for t in data.get("task_list", data.get("list", [])):
        tasks.append({
            "task_id": t.get("task_id") or t.get("id"),
            "name": t.get("task_name") or t.get("name"),
            "type": t.get("type"),
            "status": t.get("status"),
            "last_backup": ts(t.get("last_backup_time")),
        })
    return fmt({"total": len(tasks), "tasks": tasks})


@mcp.tool()
async def list_active_backup_devices() -> str:
    """List devices registered with Active Backup for Business and their transfer sizes."""
    data = check(await api.call("SYNO.ActiveBackup.Overview", "list_device_transfer_size", version=1))
    devices = []
    for d in data.get("device_list", data.get("list", [])):
        devices.append({
            "device_id": d.get("device_id") or d.get("id"),
            "name": d.get("device_name") or d.get("name"),
            "type": d.get("type"),
            "status": d.get("status"),
            "ip": d.get("ip_address") or d.get("ip"),
            "last_backup": ts(d.get("last_backup_time")),
        })
    return fmt({"total": len(devices), "devices": devices})


@mcp.tool()
async def list_cloud_sync_tasks() -> str:
    """List Cloud Sync connections and their sync status."""
    data = check(await api.call("SYNO.CloudSync", "list_conn", version=1))
    conns = []
    for c in data.get("conn", []):
        conns.append({
            "id": c.get("id"),
            "provider": c.get("type"),
            "user_name": c.get("user_name"),
            "status": c.get("status"),
            "local_path": c.get("task_path"),
            "sync_direction": c.get("sync_direction"),
        })
    return fmt({"total": len(conns), "connections": conns})


@mcp.tool()
async def manage_cloud_sync_task(connection_id: int, action: str) -> str:
    """
    Pause or resume a Cloud Sync connection. [control]

    Args:
        connection_id: Connection ID (from list_cloud_sync_tasks)
        action: "pause" or "resume"
    """
    action = action.strip().lower()
    if action not in ("pause", "resume"):
        raise ValueError("action must be 'pause' or 'resume'")
    check(await api.call("SYNO.CloudSync", action, version=1, conn_id=connection_id))
    return fmt({"connection_id": connection_id, "action": action, "ok": True})
