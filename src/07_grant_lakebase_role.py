"""Step 07 - Register the Databricks App's service principal as a Lakebase OAuth role.

WHY: a Databricks App connecting to Lakebase fails with
  `password authentication failed for user '<sp_application_id>'`
unless the SP has a Postgres role created via the `databricks_auth` extension.
A plain `CREATE ROLE` makes a *native-password* role (disabled by default) and
does NOT work for OAuth. Granting CAN_USE on the instance and attaching the
Lakebase app-resource is necessary but NOT sufficient on its own.

This must run as the instance owner (a databricks_superuser member) - i.e. the
same human who provisioned the Lakebase instance.

Run standalone:
  python src/07_grant_lakebase_role.py --profile <ws> \
      --instance <lakebase-instance> --sp <app-service-principal-application-id>

Docs: https://docs.databricks.com/aws/en/oltp/instances/pg-roles
"""
import os
import sys
import uuid
import argparse
import psycopg2

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

parser = argparse.ArgumentParser(description="Create a Lakebase OAuth role for an app SP")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit in-workspace)")
parser.add_argument("--instance", default=None, help="Lakebase instance name (default from config)")
parser.add_argument("--database", default=None, help="Database name (default from config)")
parser.add_argument("--sp", required=True, help="App service principal application/client ID")
args = parser.parse_args()

from config import LAKEBASE_INSTANCE_NAME, LAKEBASE_DATABASE_NAME  # noqa: E402
from _common import get_workspace_client  # noqa: E402

instance = args.instance or LAKEBASE_INSTANCE_NAME
database = args.database or LAKEBASE_DATABASE_NAME

w = get_workspace_client(args.profile)
inst = w.database.get_database_instance(name=instance)
cred = w.database.generate_database_credential(
    request_id=str(uuid.uuid4()), instance_names=[instance]
)
me = w.current_user.me().user_name

conn = psycopg2.connect(
    host=inst.read_write_dns, dbname=database, user=me, password=cred.token,
    port=5432, sslmode="require", connect_timeout=15,
)
conn.autocommit = True
cur = conn.cursor()

cur.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth")
cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (args.sp,))
if cur.fetchone() is None:
    cur.execute("SELECT databricks_create_role(%s, %s)", (args.sp, "SERVICE_PRINCIPAL"))
    print("databricks_create_role:", cur.fetchone()[0])
else:
    print("role already exists")

cur.execute(f'GRANT CREATE, CONNECT, TEMPORARY ON DATABASE "{database}" TO "{args.sp}"')
print(f"granted CREATE/CONNECT/TEMPORARY on {database} to {args.sp}")
cur.close()
conn.close()
print("DONE - the app SP can now authenticate to Lakebase via OAuth.")
