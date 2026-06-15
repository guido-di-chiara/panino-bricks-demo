"""Step 06 - Grant the Databricks App's service principal everything it needs.

The Multi-Agent Supervisor runs its tools AS THE CALLER (the app's service
principal). So the app SP needs:
  - CAN_QUERY on the MAS serving endpoint
  - CAN_QUERY on the KA serving endpoint
  - CAN_RUN on the Genie space
  - CAN_USE on the SQL warehouse
  - UC: USE CATALOG, USE SCHEMA, SELECT ON SCHEMA for the catalog/schema

Grants are idempotent. UC grants are issued via SQL (principal = the SP
application id in backticks). Object ACLs use the Permissions API via the SDK.

Run standalone:
  python src/06_grant_app_permissions.py --profile <ws> --catalog <cat> \
      --sp <app-sp-application-id> --mas-endpoint <name> --ka-endpoint <name> \
      --genie-space-id <id> [--warehouse-id <wh>]
"""
import os
import sys
import time
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, StatementState  # noqa: E402

parser = argparse.ArgumentParser(description="Grant app SP permissions")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit in-workspace)")
parser.add_argument("--catalog", default=None, help="Override PB_CATALOG")
parser.add_argument("--schema", default=None, help="Override PB_SCHEMA")
parser.add_argument("--sp", required=True, help="App service principal APPLICATION id (client id)")
parser.add_argument("--mas-endpoint", default=None, help="MAS serving endpoint name")
parser.add_argument("--ka-endpoint", default=None, help="KA serving endpoint name")
parser.add_argument("--genie-space-id", default=None, help="Genie space id")
parser.add_argument("--warehouse-id", default=None, help="SQL warehouse id (auto-discovered if omitted)")
args = parser.parse_args()

if args.catalog:
    os.environ["PB_CATALOG"] = args.catalog
if args.schema:
    os.environ["PB_SCHEMA"] = args.schema

from config import CATALOG, SCHEMA  # noqa: E402
from _common import get_workspace_client, discover_warehouse_id, databricks_api  # noqa: E402

w = get_workspace_client(args.profile)
warehouse_id = discover_warehouse_id(w, args.warehouse_id or os.environ.get("PB_WAREHOUSE_ID"))
SP = args.sp


def run_sql(statement, catalog=None, schema=None):
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        catalog=catalog or CATALOG,
        schema=schema or SCHEMA,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state == StatementState.FAILED:
        raise RuntimeError(f"SQL failed: {resp.status.error}\nStatement: {statement[:200]}")
    return resp


# --- 1. Unity Catalog grants (principal in backticks = the SP application id) ---
print(f"Granting UC privileges on {CATALOG}.{SCHEMA} to `{SP}`...")
run_sql(f"GRANT USE CATALOG ON CATALOG {CATALOG} TO `{SP}`", catalog="main", schema="default")
run_sql(f"GRANT USE SCHEMA ON SCHEMA {CATALOG}.{SCHEMA} TO `{SP}`")
run_sql(f"GRANT SELECT ON SCHEMA {CATALOG}.{SCHEMA} TO `{SP}`")
print("  UC grants done (USE CATALOG / USE SCHEMA / SELECT ON SCHEMA).")

# --- 2. SQL warehouse CAN_USE (Permissions API via REST) ---
print(f"Granting CAN_USE on warehouse {warehouse_id}...")
databricks_api(
    "PATCH", f"/api/2.0/permissions/warehouses/{warehouse_id}", profile=args.profile,
    body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_USE"}]},
)

# --- 3. Serving endpoint CAN_QUERY (MAS + KA) ---
for label, ep in (("MAS", args.mas_endpoint), ("KA", args.ka_endpoint)):
    if not ep:
        print(f"  (skipping {label} endpoint grant - no name provided)")
        continue
    print(f"Granting CAN_QUERY on {label} endpoint {ep}...")
    databricks_api(
        "PATCH", f"/api/2.0/permissions/serving-endpoints/{ep}", profile=args.profile,
        body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_QUERY"}]},
    )

# --- 4. Genie space CAN_RUN ---
if args.genie_space_id:
    print(f"Granting CAN_RUN on Genie space {args.genie_space_id}...")
    databricks_api(
        "PATCH", f"/api/2.0/permissions/genie/{args.genie_space_id}", profile=args.profile,
        body={"access_control_list": [{"service_principal_name": SP, "permission_level": "CAN_RUN"}]},
    )
else:
    print("  (skipping Genie grant - no space id provided)")

print("\nDONE - app SP permissions granted.")
