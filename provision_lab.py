#!/usr/bin/env python3
"""Panino Bricks lab - provisioning orchestrator.

Runs the non-DAB-native provisioning steps in order and wires the auto-named MAS
serving endpoint into the app, so that `databricks bundle deploy -t dev` can then
deploy a working app.

The flow has two phases because the app's service principal does not exist until
the app is deployed:

  PHASE A (default)  -- before `bundle deploy`:
    01 generate data        -> 13 Delta tables
    02 generate KA PDFs     -> 6 PDFs to a UC Volume
    (Lakebase instance      -> create if missing)
    03 Genie space          -> GENIE_SPACE_ID
    04 Knowledge Assistant  -> KA_ID, KA_ENDPOINT
    05 Supervisor (MAS)     -> MAS_ENDPOINT
    wire MAS_ENDPOINT into app/app.yaml + persist a state file
  ... then run: databricks bundle deploy -t dev   (creates the app + its SP)
  ... then run: python provision_lab.py --grants-only --sp <app-sp-application-id>

  PHASE B (--grants-only) -- after `bundle deploy`:
    06 grant app SP permissions (UC + endpoints + Genie + warehouse)
    07 grant app SP Lakebase OAuth role

Everything is laptop-driven via --profile. Steps are idempotent where feasible.

Examples:
  python provision_lab.py --profile my-ws --catalog panino_bricks_catalog
  python provision_lab.py --profile my-ws --grants-only --sp 1234abcd-...-app-id
"""
import os
import re
import sys
import json
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
STATE_FILE = os.path.join(HERE, ".lab_state.json")
APP_YAML = os.path.join(HERE, "app", "app.yaml")


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print(f"  [state] wrote {STATE_FILE}")


def run_step(script: str, extra_args: list[str], env: dict) -> str:
    """Run a src/ step as a subprocess; stream output; return captured stdout."""
    path = os.path.join(SRC, script)
    cmd = [sys.executable, path] + extra_args
    print(f"\n=== {script} ===")
    print("  $ " + " ".join(cmd))
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.stderr:
        sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        sys.exit(f"Step {script} failed (exit {proc.returncode}).")
    return proc.stdout


def grep_kv(stdout: str, key: str) -> str | None:
    """Extract `KEY=value` printed on its own line by a step."""
    m = re.search(rf"^{re.escape(key)}=(.+)$", stdout, re.MULTILINE)
    return m.group(1).strip() if m else None


def ensure_lakebase(profile: str | None, instance: str):
    """Create the Lakebase instance if it does not already exist (idempotent)."""
    base = ["databricks"]
    if profile:
        base += ["-p", profile]
    show = subprocess.run(
        base + ["database", "get-database-instance", instance],
        capture_output=True, text=True,
    )
    if show.returncode == 0:
        print(f"  Lakebase instance '{instance}' already exists.")
        return
    print(f"  Creating Lakebase instance '{instance}' (CU_1, pg-native-login)...")
    create = subprocess.run(
        base + ["database", "create-database-instance", instance,
                "--capacity", "CU_1", "--enable-pg-native-login"],
        capture_output=True, text=True,
    )
    sys.stdout.write(create.stdout)
    if create.returncode != 0:
        sys.stderr.write(create.stderr)
        sys.exit("Failed to create Lakebase instance. Check region / serverless budget policy.")


def wire_app_yaml(mas_endpoint: str, catalog: str, schema: str, instance: str, database: str):
    """Rewrite app/app.yaml env values in place so the deployed app is correct."""
    with open(APP_YAML) as f:
        text = f.read()
    repl = {
        "MAS_ENDPOINT_NAME": mas_endpoint,
        "PB_CATALOG": catalog,
        "PB_SCHEMA": schema,
        "LAKEBASE_INSTANCE_NAME": instance,
        "LAKEBASE_DATABASE_NAME": database,
    }
    for name, value in repl.items():
        # Replace the `value: "..."` that follows `- name: <name>`.
        text = re.sub(
            rf'(- name: {name}\s*\n\s*value: )"[^"]*"',
            rf'\1"{value}"',
            text,
        )
    with open(APP_YAML, "w") as f:
        f.write(text)
    print(f"  [app.yaml] MAS_ENDPOINT_NAME={mas_endpoint}, catalog={catalog}, schema={schema}")


def phase_a(args, env):
    state = load_state()
    common = []
    if args.profile:
        common += ["--profile", args.profile]
    cat_args = common + ["--catalog", args.catalog, "--schema", args.schema]
    wh_args = (["--warehouse-id", args.warehouse_id] if args.warehouse_id else [])

    # 01 data
    run_step("01_generate_data.py", cat_args + wh_args, env)
    # 02 KA PDFs
    run_step("02_generate_ka_documents.py", cat_args, env)
    # Lakebase instance
    ensure_lakebase(args.profile, args.lakebase_instance)
    # 03 Genie
    out = run_step("03_create_genie_space.py", cat_args + wh_args, env)
    state["genie_space_id"] = grep_kv(out, "GENIE_SPACE_ID")
    # 04 KA
    out = run_step("04_create_knowledge_assistant.py", cat_args, env)
    state["ka_id"] = grep_kv(out, "KA_ID")
    state["ka_endpoint"] = grep_kv(out, "KA_ENDPOINT")
    # 05 MAS
    out = run_step("05_create_supervisor_agent.py", common + [
        "--genie-space-id", state["genie_space_id"] or "",
        "--ka-id", state["ka_id"] or "",
        "--ka-endpoint", state["ka_endpoint"] or "",
    ], env)
    state["mas_endpoint"] = grep_kv(out, "MAS_ENDPOINT")

    state.update({
        "catalog": args.catalog, "schema": args.schema,
        "warehouse_id": args.warehouse_id or "",
        "lakebase_instance": args.lakebase_instance,
        "lakebase_database": args.lakebase_database,
    })
    save_state(state)

    if state.get("mas_endpoint"):
        wire_app_yaml(state["mas_endpoint"], args.catalog, args.schema,
                      args.lakebase_instance, args.lakebase_database)

    print_summary_a(args, state)


def phase_b(args, env):
    state = load_state()
    catalog = state.get("catalog", args.catalog)
    schema = state.get("schema", args.schema)
    common = (["--profile", args.profile] if args.profile else [])

    # 06 grants
    run_step("06_grant_app_permissions.py", common + [
        "--catalog", catalog, "--schema", schema, "--sp", args.sp,
        "--mas-endpoint", state.get("mas_endpoint") or "",
        "--ka-endpoint", state.get("ka_endpoint") or "",
        "--genie-space-id", state.get("genie_space_id") or "",
    ] + (["--warehouse-id", state.get("warehouse_id")] if state.get("warehouse_id") else []), env)

    # 07 Lakebase role
    run_step("07_grant_lakebase_role.py", common + [
        "--instance", state.get("lakebase_instance", args.lakebase_instance),
        "--database", state.get("lakebase_database", args.lakebase_database),
        "--sp", args.sp,
    ], env)

    print("\n========================================")
    print("Grants complete. The app SP can now query the MAS/KA endpoints, run the")
    print("Genie space, use the warehouse, read the catalog, and authenticate to Lakebase.")
    print("Re-deploy or restart the app if it was already running: databricks bundle deploy -t dev")
    print("========================================")


def print_summary_a(args, state):
    print("\n========================================")
    print("PHASE A complete. Created / verified:")
    print(f"  catalog.schema   : {args.catalog}.{args.schema}")
    print(f"  Genie space id   : {state.get('genie_space_id')}")
    print(f"  KA id / endpoint : {state.get('ka_id')} / {state.get('ka_endpoint')}")
    print(f"  MAS endpoint     : {state.get('mas_endpoint')}")
    print(f"  Lakebase         : {args.lakebase_instance} / {args.lakebase_database}")
    print("\nNEXT:")
    print(f"  1) databricks bundle deploy -t dev --var=\"mas_endpoint_name={state.get('mas_endpoint')}\""
          f" --var=\"catalog={args.catalog}\" --var=\"schema={args.schema}\""
          + (f" -p {args.profile}" if args.profile else ""))
    print("     (this creates the app and its service principal)")
    print("  2) Find the app SP application id in the app's resource page, then:")
    print(f"     python provision_lab.py {('--profile ' + args.profile + ' ') if args.profile else ''}"
          "--grants-only --sp <app-sp-application-id>")
    print("========================================")


def main():
    ap = argparse.ArgumentParser(description="Panino Bricks lab provisioning orchestrator")
    ap.add_argument("--profile", default=None, help="Databricks CLI profile (omit only when in-workspace)")
    ap.add_argument("--catalog", default=os.environ.get("PB_CATALOG", "panino_bricks_catalog"))
    ap.add_argument("--schema", default=os.environ.get("PB_SCHEMA", "panino_bricks"))
    ap.add_argument("--warehouse-id", default=os.environ.get("PB_WAREHOUSE_ID"))
    ap.add_argument("--lakebase-instance", default="panino-bricks")
    ap.add_argument("--lakebase-database", default="databricks_postgres")
    ap.add_argument("--grants-only", action="store_true",
                    help="PHASE B: run steps 06+07 (requires --sp). Run after `bundle deploy`.")
    ap.add_argument("--sp", default=None, help="App service principal application id (PHASE B)")
    args = ap.parse_args()

    # Child steps read config from env; propagate the chosen catalog/schema/warehouse.
    env = dict(os.environ)
    env["PB_CATALOG"] = args.catalog
    env["PB_SCHEMA"] = args.schema
    if args.warehouse_id:
        env["PB_WAREHOUSE_ID"] = args.warehouse_id

    if args.grants_only:
        if not args.sp:
            sys.exit("--grants-only requires --sp <app-service-principal-application-id>")
        phase_b(args, env)
    else:
        phase_a(args, env)


if __name__ == "__main__":
    main()
