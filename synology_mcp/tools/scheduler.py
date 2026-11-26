"""Task Scheduler tools: list, inspect, create, update, enable/disable, run, and delete scheduled tasks."""

from __future__ import annotations

import json
from typing import Any

from .. import api
from ..app import check, fmt, mcp

_DEFAULT_SCHEDULE: dict[str, Any] = {
    "date_type": 0,
    "week_day": "0,1,2,3,4,5,6",
    "repeat_date": 1001,
    "repeat_min": 0,
    "last_work_hour": 0,
    "hour": 2,
    "minute": 0,
}


@mcp.tool()
async def list_scheduled_tasks() -> str:
    """List scheduled tasks (cron jobs, scripts, scheduled backups, etc.)."""
    data = check(await api.call("SYNO.Core.TaskScheduler", "list", version=1))
    tasks = []
    for t in data.get("tasks", []):
        tasks.append({
            "id": t.get("id"),
            "name": t.get("name"),
            "type": t.get("type"),
            "enabled": t.get("enable"),
            "owner": t.get("owner"),
            "next_run": t.get("next_trigger_time"),
            "can_run_now": t.get("can_run"),
        })
    return fmt({"total": data.get("total", len(tasks)), "tasks": tasks})


@mcp.tool()
async def get_scheduled_task(task_id: int) -> str:
    """
    Get full details (schedule, script, owner, notification settings) for a scheduled task.

    Args:
        task_id: Numeric task id (from list_scheduled_tasks)
    """
    data = check(await api.call("SYNO.Core.TaskScheduler", "get", version=1, id=task_id))
    return fmt(data)


@mcp.tool()
async def run_scheduled_task(task_id: int) -> str:
    """
    Trigger a scheduled task to run immediately. [control]

    Args:
        task_id: Numeric task id (from list_scheduled_tasks)
    """
    check(await api.call("SYNO.Core.TaskScheduler", "run", version=1, taskId=task_id))
    return fmt({"task_id": task_id, "triggered": True})


@mcp.tool()
async def set_scheduled_task_enabled(task_id: int, enabled: bool) -> str:
    """
    Enable or disable an existing scheduled task. [control]

    Args:
        task_id: Numeric task id (from list_scheduled_tasks)
        enabled: True to enable, False to disable
    """
    status_payload = json.dumps([{"id": task_id, "enable": enabled}])
    check(await api.call(
        "SYNO.Core.TaskScheduler",
        "set_enable",
        version=1,
        http_method="POST",
        status=status_payload,
    ))
    return fmt({"task_id": task_id, "enabled": enabled, "ok": True})


@mcp.tool()
async def create_scheduled_task(
    name: str,
    script: str,
    owner: str = "root",
    hour: int = 2,
    minute: int = 0,
    week_day: str = "0,1,2,3,4,5,6",
    enabled: bool = True,
    notify_enable: bool = False,
    notify_mail: str = "",
    notify_if_error: bool = False,
    schedule: dict[str, Any] | None = None,
) -> str:
    """
    Create a new user-defined script scheduled task in DSM Task Scheduler. [control]

    Args:
        name: Task name
        script: Shell script content to run
        owner: User to run as (default "root")
        hour: Run hour 0-23 when schedule is omitted (default 2)
        minute: Run minute 0-59 when schedule is omitted (default 0)
        week_day: Comma-separated days 0=Sun..6=Sat when schedule is omitted (default every day)
        enabled: Whether the task is enabled (default True)
        notify_enable: Send email notification on run (default False)
        notify_mail: Notification email address
        notify_if_error: Only notify on non-zero exit (default False)
        schedule: Optional full DSM schedule dict overriding hour/minute/week_day
    """
    sched = schedule if schedule is not None else {
        **_DEFAULT_SCHEDULE,
        "hour": hour,
        "minute": minute,
        "week_day": week_day,
    }
    extra = {
        "script": script,
        "notify_enable": notify_enable,
        "notify_mail": notify_mail,
        "notify_if_error": notify_if_error,
    }
    api_name = "SYNO.Core.TaskScheduler.Root" if owner == "root" else "SYNO.Core.TaskScheduler"
    data = check(await api.call(
        api_name,
        "create",
        version=4,
        http_method="POST",
        type="script",
        name=name,
        owner=owner,
        enable="true" if enabled else "false",
        schedule=json.dumps(sched),
        extra=json.dumps(extra),
    ))
    return fmt({"created": True, "name": name, "owner": owner, "data": data})


@mcp.tool()
async def update_scheduled_task(
    task_id: int,
    name: str | None = None,
    script: str | None = None,
    enabled: bool | None = None,
    schedule: dict[str, Any] | None = None,
) -> str:
    """
    Update an existing scheduled script task in DSM Task Scheduler. [control]

    Args:
        task_id: Numeric task id (from list_scheduled_tasks)
        name: Optional new task name
        script: Optional new shell script content
        enabled: Optional new enabled state
        schedule: Optional new DSM schedule dict
    """
    current = check(await api.call("SYNO.Core.TaskScheduler", "get", version=1, id=task_id))
    owner = current.get("owner", "root")
    new_name = name if name is not None else current.get("name", "")
    new_enabled = enabled if enabled is not None else bool(current.get("enable", True))
    new_sched = schedule if schedule is not None else current.get("schedule", _DEFAULT_SCHEDULE)
    extra = dict(current.get("extra") or {})
    if script is not None:
        extra["script"] = script

    api_name = "SYNO.Core.TaskScheduler.Root" if owner == "root" else "SYNO.Core.TaskScheduler"
    data = check(await api.call(
        api_name,
        "set",
        version=4,
        http_method="POST",
        id=task_id,
        type=current.get("type", "script"),
        name=new_name,
        owner=owner,
        enable="true" if new_enabled else "false",
        schedule=json.dumps(new_sched),
        extra=json.dumps(extra),
    ))
    return fmt({"updated": True, "task_id": task_id, "data": data})


@mcp.tool()
async def delete_scheduled_task(task_id: int) -> str:
    """
    Delete a scheduled task from DSM Task Scheduler. [control]

    Args:
        task_id: Numeric task id (from list_scheduled_tasks)
    """
    check(await api.call(
        "SYNO.Core.TaskScheduler",
        "delete",
        version=1,
        http_method="POST",
        tasks=json.dumps([task_id]),
    ))
    return fmt({"deleted": True, "task_id": task_id})
