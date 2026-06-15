"""Shared helpers for the Panino Bricks lab provisioning scripts.

Provides:
  - `get_workspace_client(profile)`: a WorkspaceClient that uses the CLI profile
    when running on a laptop, or ambient auth when running inside a Databricks
    runtime (notebook/job, detected via DATABRICKS_RUNTIME_VERSION).
  - `cli_base(profile)`: the base argv for `databricks ...` CLI calls, including
    `-p <profile>` only when a profile is set (in-workspace runs omit it).
  - `databricks_api(...)`: a thin REST wrapper over `databricks api` that passes
    the JSON body via a temp file (`--json @file`) — the proven-reliable form for
    the Agent Bricks endpoints whose responses the Python SDK 0.114 fails to parse.
"""
from __future__ import annotations

import os
import sys
import json
import tempfile
import subprocess

from databricks.sdk import WorkspaceClient


def in_workspace() -> bool:
    """True when running inside a Databricks runtime (ambient auth available)."""
    return bool(os.environ.get("DATABRICKS_RUNTIME_VERSION"))


def get_workspace_client(profile: str | None = None) -> WorkspaceClient:
    """WorkspaceClient using the CLI profile locally, or ambient auth in-workspace."""
    if in_workspace() or not profile:
        return WorkspaceClient()
    return WorkspaceClient(profile=profile)


def cli_base(profile: str | None) -> list[str]:
    """Base argv for `databricks` CLI calls. Adds `-p <profile>` only when set."""
    base = ["databricks"]
    if profile and not in_workspace():
        base += ["-p", profile]
    return base


def databricks_api(method: str, path: str, profile: str | None = None,
                   body: dict | None = None, query: dict | None = None):
    """Call the Databricks REST API via the CLI.

    Returns (parsed_json_or_None, stderr_or_raw_text). We call REST directly
    because the Python SDK 0.114 fails to *parse* create responses for
    knowledge_assistants / supervisor_agents even though the server succeeds.
    """
    p = path
    if query:
        p += "?" + "&".join(f"{k}={v}" for k, v in query.items())
    cmd = ["databricks", "api", method, p]
    if profile and not in_workspace():
        cmd += ["-p", profile]
    if body is not None:
        tf = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(body, tf)
        tf.close()
        cmd += ["--json", f"@{tf.name}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(out.stdout), out.stderr
    except json.JSONDecodeError:
        return None, (out.stderr or out.stdout)


def discover_warehouse_id(w: WorkspaceClient, explicit: str | None = None) -> str:
    """Return the explicit warehouse id, else auto-discover (prefer RUNNING)."""
    if explicit:
        return explicit
    warehouses = list(w.warehouses.list())
    if not warehouses:
        sys.exit("No SQL warehouses found. Provide --warehouse-id or create one.")
    running = [wh for wh in warehouses if wh.state and wh.state.value == "RUNNING"]
    chosen = running[0] if running else warehouses[0]
    print(f"  Using warehouse: {chosen.name} ({chosen.id})")
    return chosen.id
