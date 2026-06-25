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
    """Call the Databricks REST API via the SDK HTTP client.

    Returns (parsed_json_or_None, error_string). Uses api_client.do() to bypass
    the SDK model-parsing layer — avoids SDK parse failures for
    knowledge_assistants / supervisor_agents while working in-process with
    ambient auth (no CLI subprocess needed).
    """
    w = get_workspace_client(profile)
    try:
        resp = w.api_client.do(method, path, body=body, query=query)
        return resp, None
    except Exception as e:
        return None, str(e)


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


import io, os, re, runpy, sys

sys.dont_write_bytecode = True  # prevent __pycache__ errors on serverless

try:
    _HERE = "/Workspace" + os.path.dirname(
        dbutils.notebook.entry_point.getDbutils().notebook().getContext().notebookPath().get()
    )
except:
    _HERE = os.getcwd()

def run_script(script_name, **params):
    """Run a Python script in-process, forwarding non-empty kwargs as CLI --key=value args.
    Returns a dict of KEY=VALUE lines printed by the script (for chaining between steps)."""
    script = os.path.join(_HERE, script_name)
    sys.argv = [script] + [f"--{k.replace('_', '-')}={v}" for k, v in params.items() if v != ""]

    _buf, _orig = io.StringIO(), sys.stdout

    class _Tee:
        def write(self, s):  _orig.write(s); _buf.write(s)
        def flush(self):     _orig.flush()
        def __getattr__(self, n): return getattr(_orig, n)

    sys.stdout = _Tee()
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        sys.stdout = _orig

    # Parse KEY=VALUE lines (e.g. GENIE_SPACE_ID=abc123) from the script output
    outputs = {}
    for line in _buf.getvalue().splitlines():
        m = re.match(r'^([A-Z][A-Z0-9_]+)=(.+)', line.strip())
        if m:
            outputs[m.group(1)] = m.group(2)
    return outputs
