"""Central configuration for the Panino Bricks lab.

Single source of truth for branding, catalog, schema, volumes, and resource names.
Every value is overridable via an environment variable so the SAME code runs:
  - on a laptop (driven by `provision_lab.py --profile <ws> --catalog <cat>`),
  - inside a Databricks App (env injected from app.yaml / resources/app.yml), and
  - inside a Databricks notebook / job (ambient auth).

NOTHING here is hardcoded to a specific workspace. The defaults are generic and
meant to be overridden by `provision_lab.py` (which exports the env vars) or by
the bundle / app config.
"""

import os

# --- Branding (the only place the brand name lives) -------------------------
BRAND_NAME = os.environ.get("PB_BRAND_NAME", "Panino Bricks")
BRAND_TAGLINE = os.environ.get("PB_BRAND_TAGLINE", "powered by Databricks and Lakebase")
BRAND_DESCRIPTION = os.environ.get(
    "PB_BRAND_DESCRIPTION",
    "Panino Bricks è una catena italiana di paninoteche con sedi in tutta Italia. "
    "Questo assistente aiuta lo staff a trovare ricette, controllare vendite e scorte, "
    "esplorare promozioni e rispondere a domande operative — il tutto con un sistema "
    "multi-agente AI su Databricks.",
)
BRAND_PAGE_ICON = os.environ.get("PB_BRAND_PAGE_ICON", "🥪")
STORE_PREFIX = BRAND_NAME  # used as "{STORE_PREFIX} Milano" etc.

# --- Unity Catalog ----------------------------------------------------------
# IMPORTANT: on a fresh FEVM/serverless workspace the catalog must be created via
# the UI with Default Storage (a plain `CREATE CATALOG` fails with
# "Metastore storage root URL does not exist"). The scripts only `USE CATALOG`
# (verify it exists) and then create the schema + volumes inside it.
CATALOG = os.environ.get("PB_CATALOG", "panino_bricks_catalog")
SCHEMA = os.environ.get("PB_SCHEMA", "panino_bricks")
VOLUME_NAME = os.environ.get("PB_VOLUME_NAME", "raw_data")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME_NAME}"
KA_VOLUME_NAME = os.environ.get("PB_KA_VOLUME_NAME", "ka_documents")
KA_VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{KA_VOLUME_NAME}"

# --- Compute ----------------------------------------------------------------
# SQL warehouse used to create Delta tables. If empty, scripts auto-discover one.
WAREHOUSE_ID = os.environ.get("PB_WAREHOUSE_ID", "")

# --- Serving / Lakebase resources -------------------------------------------
# MAS_ENDPOINT_NAME is the Agent Bricks Multi-Agent Supervisor serving endpoint.
# Agent Bricks AUTO-NAMES it `mas-<hash>-endpoint` at creation time, so it is NOT
# known ahead of provisioning. `provision_lab.py` captures the created name and
# wires it into the app (app.yaml / resources/app.yml env MAS_ENDPOINT_NAME).
# The empty default is intentional: the app reads it from its injected env.
MAS_ENDPOINT_NAME = os.environ.get("MAS_ENDPOINT_NAME", "")
LAKEBASE_INSTANCE_NAME = os.environ.get("LAKEBASE_INSTANCE_NAME", "panino-bricks")
LAKEBASE_DATABASE_NAME = os.environ.get("LAKEBASE_DATABASE_NAME", "databricks_postgres")

# --- Genie / Knowledge Assistant titles (used for idempotent lookup) --------
GENIE_SPACE_TITLE = os.environ.get("PB_GENIE_TITLE", f"{BRAND_NAME} - Vendite & Operations")
KA_DISPLAY_NAME = os.environ.get("PB_KA_NAME", f"{BRAND_NAME} - Assistente Operativo")
SUPERVISOR_DISPLAY_NAME = os.environ.get("PB_SUPERVISOR_NAME", f"{BRAND_NAME} HQ")

# --- Localization -----------------------------------------------------------
LOCALE = "it_IT"
CURRENCY = "EUR"
CURRENCY_SYMBOL = "€"
COUNTRY = "Italy"
