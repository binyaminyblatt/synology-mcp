"""Snapshot Replication tools: list, create and delete Btrfs snapshots and replication tasks."""

from __future__ import annotations

import json

from .. import api
from ..app import check, fmt, mcp, ts


@mcp.tool()
async def list_snapshots(shared_folder: str) -> str:
    """
    List all Btrfs snapshots for a shared folder.

    Args:
        shared_folder: Shared folder name (e.g. "docker", "homes", "data")
    """
    data = check(await api.call(
        "SYNO.Core.Share.Snapshot", "list", version=1,
        name=shared_folder,
    ))
    snapshots = []
    for s in data.get("snapshots", data.get("list", [])):
        snapshots.append({
            "time": s.get("time") if isinstance(s.get("time"), str) else ts(s.get("time") or s.get("create_time")),
            "description": s.get("desc") or s.get("description") or None,
            "locked": bool(s.get("lock") or s.get("is_locked")),
            "schedule": s.get("schedule_snapshot"),
        })
    return fmt({
        "shared_folder": shared_folder,
        "total": data.get("total", len(snapshots)),
        "snapshots": snapshots,
    })


@mcp.tool()
async def create_snapshot(
    shared_folder: str,
    description: str = "",
    locked: bool = False,
) -> str:
    """
    Create a new Btrfs snapshot of a shared folder. [control]

    Args:
        shared_folder: Shared folder name (e.g. "docker", "homes")
        description: Optional snapshot note/description
        locked: Lock the snapshot to prevent automatic retention deletion (default False)
    """
    snapinfo = json.dumps({"desc": description, "lock": bool(locked)})
    data = check(await api.call(
        "SYNO.Core.Share.Snapshot", "create", version=1,
        name=shared_folder, snapinfo=snapinfo,
    ))
    return fmt({
        "shared_folder": shared_folder,
        "created_snapshot": data,
        "description": description or None,
        "locked": locked,
    })


@mcp.tool()
async def delete_snapshot(shared_folder: str, snapshot_times: str) -> str:
    """
    Delete one or more Btrfs snapshots from a shared folder. [control]

    Args:
        shared_folder: Shared folder name
        snapshot_times: Comma-separated snapshot time identifiers (from list_snapshots, e.g. "GMT+02-2026.11.26-12.00.00")
    """
    items = [s.strip() for s in snapshot_times.split(",") if s.strip()]
    check(await api.call(
        "SYNO.Core.Share.Snapshot", "delete", version=1,
        name=shared_folder, snapshots=json.dumps(items),
    ))
    return fmt({"shared_folder": shared_folder, "deleted": items})
