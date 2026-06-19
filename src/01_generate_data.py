"""Step 01 - Generate synthetic data for the Panino Bricks Italian panino chain.

Writes 13 Delta tables to Databricks Unity Catalog via the Databricks SDK.
Requires: pip install -r requirements.txt
Catalog/schema and branding come from the repo-root config.py (single source of truth).

Run standalone (laptop):
  python src/01_generate_data.py --profile <ws> --catalog <cat> [--warehouse-id <wh>]
Run in a Databricks notebook/job (ambient auth): import and call main().

Prerequisite: the catalog (PB_CATALOG) must already exist, created via the UI
with Default Storage. This script only does USE CATALOG (verify) + CREATE SCHEMA/VOLUME.
"""
import io
import os
import sys
import time
import argparse
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from faker import Faker
import holidays
from databricks.sdk.service.sql import ExecuteStatementRequestOnWaitTimeout, StatementState

# Make the repo-root config + src/_common importable regardless of cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

N_CUSTOMERS = 15000
N_ORDERS = 200000

# Analytics data window for the demo: 1 Apr -> 30 June 2026 (3 full months for clean MoM, ends on event day).
END_DATE = datetime(2026, 6, 30)
START_DATE = datetime(2026, 4, 1)

# Summer promo within the data window (early-to-mid June)
MANGO_PROMO_START = END_DATE - timedelta(days=29)
MANGO_PROMO_END = END_DATE - timedelta(days=16)

# Newest store opening spike (~19 May — inside the window, so the spike shows)
NEW_STORE_OPEN = END_DATE - timedelta(days=42)

# All Panino Bricks stores are in Italy — single national holiday calendar.
COUNTRY_HOLIDAYS = {
    "Italy": holidays.IT(years=[START_DATE.year, END_DATE.year]),
}
SEED = 42

# =============================================================================
# SETUP
# =============================================================================
np.random.seed(SEED)
Faker.seed(SEED)
fake = Faker("it_IT")

# --- Databricks SDK connection ---
parser = argparse.ArgumentParser(description="Generate Panino Bricks synthetic data")
parser.add_argument("--warehouse-id", default=None, help="SQL warehouse ID (auto-discovered if omitted)")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit when running in-workspace)")
parser.add_argument("--catalog",  default=None, help="Override PB_CATALOG (else config default / env)")
parser.add_argument("--schema",   default=None, help="Override PB_SCHEMA (else config default / env)")
parser.add_argument("--n-orders", default=None, type=int, help="Override N_ORDERS (scales store volumes proportionally)")
args = parser.parse_args()

# Let CLI flags override the env BEFORE config is imported (config reads env).
if args.catalog:
    os.environ["PB_CATALOG"] = args.catalog
if args.schema:
    os.environ["PB_SCHEMA"] = args.schema
if args.n_orders:
    N_ORDERS = args.n_orders

from config import CATALOG, SCHEMA, VOLUME_PATH, BRAND_NAME, STORE_PREFIX  # noqa: E402,F401
from _common import get_workspace_client, discover_warehouse_id  # noqa: E402

print("Connecting to Databricks workspace...")
w = get_workspace_client(args.profile)
print(f"  Host: {w.config.host}")

print("  Resolving SQL warehouse...")
warehouse_id = discover_warehouse_id(w, args.warehouse_id or os.environ.get("PB_WAREHOUSE_ID"))


def run_sql(statement, catalog=None, schema=None):
    """Execute SQL via Statement Execution API and wait for completion."""
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        catalog=catalog if catalog is not None else CATALOG,
        schema=schema if schema is not None else SCHEMA,
        wait_timeout="50s",
        on_wait_timeout=ExecuteStatementRequestOnWaitTimeout.CONTINUE,
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state == StatementState.FAILED:
        raise RuntimeError(f"SQL failed: {resp.status.error}\nStatement: {statement[:200]}")
    return resp


def upload_and_create_table(table_name, df):
    """Upload a pandas DataFrame as Parquet to a Volume, then create a Delta table."""
    parquet_buffer = io.BytesIO()
    df.to_parquet(parquet_buffer, index=False, engine="pyarrow")
    parquet_buffer.seek(0)

    volume_path = f"/Volumes/{CATALOG}/{SCHEMA}/raw_data/{table_name}.parquet"
    w.files.upload(volume_path, parquet_buffer, overwrite=True)
    print(f"    Uploaded {table_name}.parquet ({len(df):,} rows)")

    sql = f"""
    CREATE OR REPLACE TABLE {CATALOG}.{SCHEMA}.{table_name}
    AS SELECT * FROM read_files(
        '{volume_path}',
        format => 'parquet'
    )
    """
    run_sql(sql)
    print(f"    Created table {CATALOG}.{SCHEMA}.{table_name}")

# =============================================================================
# CREATE INFRASTRUCTURE
# =============================================================================
print("Setting up catalog/schema/volume...")
# Catalog must be created via Databricks UI (Default Storage requirement)
# Verify it exists, then create schema
run_sql(f"USE CATALOG {CATALOG}", catalog="main", schema="default")
print(f"  Catalog {CATALOG} exists")
run_sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{SCHEMA}", catalog=CATALOG, schema="default")
run_sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{SCHEMA}.raw_data")
print(f"  Volume ready at {VOLUME_PATH}")

# =============================================================================
# 1. STORES
# =============================================================================
print("Generating stores...")

# Store metadata: country, tax rate, hemisphere (for seasonal adjustments), holiday key
# All stores are in Italy: uniform 10% IVA (ristorazione/asporto), N hemisphere, IT holidays.
_STORE_IDS = [
    "STR-005", "STR-006", "STR-007", "STR-009", "STR-010", "STR-011", "STR-012",
    "STR-013", "STR-014", "STR-015", "STR-016", "STR-017", "STR-018", "STR-019",
    "STR-020", "STR-021", "STR-022", "STR-023", "STR-024", "STR-025", "STR-026",
    "STR-027", "STR-028", "STR-029", "STR-030", "STR-031", "STR-032", "STR-033",
    "STR-034", "STR-035", "STR-036", "STR-037", "STR-038", "STR-039", "STR-040",
    "STR-041", "STR-042",
]
STORE_META = {
    sid: {"country": "Italy", "tax_rate": 0.10, "hemisphere": "N", "holiday_key": "Italy"}
    for sid in _STORE_IDS
}

stores_data = [
    # Italian panino chain (STR-005 through STR-042). store_id / sq_footage /
    # seating_capacity / opened_date preserved from the original to keep the
    # volume simulation (store age tiers, new-store spikes) identical.
    {"store_id": "STR-005", "name": f"{STORE_PREFIX} Milano Navigli",      "city": "Milano",   "state": "Lombardia",            "neighborhood": "Navigli",            "sq_footage": 780, "seating_capacity": 20, "opened_date": "2022-06-01"},
    {"store_id": "STR-006", "name": f"{STORE_PREFIX} Milano Brera",        "city": "Milano",   "state": "Lombardia",            "neighborhood": "Brera",              "sq_footage": 650, "seating_capacity": 14, "opened_date": "2022-09-15"},
    {"store_id": "STR-007", "name": f"{STORE_PREFIX} Roma Trastevere",     "city": "Roma",     "state": "Lazio",                "neighborhood": "Trastevere",         "sq_footage": 850, "seating_capacity": 22, "opened_date": "2022-11-01"},
    {"store_id": "STR-009", "name": f"{STORE_PREFIX} Bologna Centro",      "city": "Bologna",  "state": "Emilia-Romagna",       "neighborhood": "Quadrilatero",       "sq_footage": 580, "seating_capacity": 12, "opened_date": "2024-03-01"},
    {"store_id": "STR-010", "name": f"{STORE_PREFIX} Torino San Salvario", "city": "Torino",   "state": "Piemonte",             "neighborhood": "San Salvario",       "sq_footage": 720, "seating_capacity": 16, "opened_date": "2023-08-10"},
    {"store_id": "STR-011", "name": f"{STORE_PREFIX} Firenze Oltrarno",    "city": "Firenze",  "state": "Toscana",              "neighborhood": "Oltrarno",           "sq_footage": 600, "seating_capacity": 14, "opened_date": "2024-06-15"},
    {"store_id": "STR-012", "name": f"{STORE_PREFIX} Napoli Chiaia",       "city": "Napoli",   "state": "Campania",             "neighborhood": "Chiaia",             "sq_footage": 550, "seating_capacity": 10, "opened_date": "2024-09-01"},
    {"store_id": "STR-013", "name": f"{STORE_PREFIX} Roma Monti",          "city": "Roma",     "state": "Lazio",                "neighborhood": "Monti",              "sq_footage": 680, "seating_capacity": 16, "opened_date": "2023-04-20"},
    {"store_id": "STR-014", "name": f"{STORE_PREFIX} Verona Centro",       "city": "Verona",   "state": "Veneto",               "neighborhood": "Città Antica",       "sq_footage": 540, "seating_capacity": 10, "opened_date": "2024-07-01"},
    {"store_id": "STR-015", "name": f"{STORE_PREFIX} Padova Centro",       "city": "Padova",   "state": "Veneto",               "neighborhood": "Portello",           "sq_footage": 620, "seating_capacity": 12, "opened_date": "2024-01-15"},
    {"store_id": "STR-016", "name": f"{STORE_PREFIX} Genova Centro",       "city": "Genova",   "state": "Liguria",              "neighborhood": "Maddalena",          "sq_footage": 580, "seating_capacity": 12, "opened_date": "2024-05-01"},
    {"store_id": "STR-017", "name": f"{STORE_PREFIX} Bari Murat",          "city": "Bari",     "state": "Puglia",               "neighborhood": "Murat",              "sq_footage": 520, "seating_capacity": 10, "opened_date": "2024-08-15"},
    {"store_id": "STR-018", "name": f"{STORE_PREFIX} Milano Isola",        "city": "Milano",   "state": "Lombardia",            "neighborhood": "Isola",              "sq_footage": 750, "seating_capacity": 18, "opened_date": "2023-06-01"},
    {"store_id": "STR-019", "name": f"{STORE_PREFIX} Bergamo Bassa",       "city": "Bergamo",  "state": "Lombardia",            "neighborhood": "Città Bassa",        "sq_footage": 700, "seating_capacity": 16, "opened_date": "2023-10-01"},
    {"store_id": "STR-020", "name": f"{STORE_PREFIX} Roma EUR",            "city": "Roma",     "state": "Lazio",                "neighborhood": "EUR",                "sq_footage": 900, "seating_capacity": 24, "opened_date": "2024-02-01"},
    {"store_id": "STR-021", "name": f"{STORE_PREFIX} Brescia Centro",      "city": "Brescia",  "state": "Lombardia",            "neighborhood": "Carmine",            "sq_footage": 560, "seating_capacity": 12, "opened_date": "2024-04-15"},
    {"store_id": "STR-022", "name": f"{STORE_PREFIX} Parma Centro",        "city": "Parma",    "state": "Emilia-Romagna",       "neighborhood": "Oltretorrente",      "sq_footage": 600, "seating_capacity": 14, "opened_date": "2024-06-01"},
    {"store_id": "STR-023", "name": f"{STORE_PREFIX} Modena Centro",       "city": "Modena",   "state": "Emilia-Romagna",       "neighborhood": "Centro Storico",     "sq_footage": 500, "seating_capacity": 10, "opened_date": "2024-10-01"},
    {"store_id": "STR-024", "name": f"{STORE_PREFIX} Trieste Centro",      "city": "Trieste",  "state": "Friuli-Venezia Giulia","neighborhood": "Borgo Teresiano",    "sq_footage": 480, "seating_capacity": 8,  "opened_date": "2024-01-01"},
    {"store_id": "STR-025", "name": f"{STORE_PREFIX} Venezia Mestre",      "city": "Venezia",  "state": "Veneto",               "neighborhood": "Mestre",             "sq_footage": 620, "seating_capacity": 14, "opened_date": "2024-05-15"},
    {"store_id": "STR-026", "name": f"{STORE_PREFIX} Trento Centro",       "city": "Trento",   "state": "Trentino-Alto Adige",  "neighborhood": "Centro Storico",     "sq_footage": 500, "seating_capacity": 10, "opened_date": "2024-11-01"},
    {"store_id": "STR-027", "name": f"{STORE_PREFIX} Torino Quadrilatero", "city": "Torino",   "state": "Piemonte",             "neighborhood": "Quadrilatero Romano","sq_footage": 680, "seating_capacity": 16, "opened_date": "2023-09-01"},
    {"store_id": "STR-028", "name": f"{STORE_PREFIX} Palermo Centro",      "city": "Palermo",  "state": "Sicilia",              "neighborhood": "Vucciria",           "sq_footage": 640, "seating_capacity": 14, "opened_date": "2024-02-15"},
    {"store_id": "STR-029", "name": f"{STORE_PREFIX} Catania Centro",      "city": "Catania",  "state": "Sicilia",              "neighborhood": "Via Etnea",          "sq_footage": 560, "seating_capacity": 12, "opened_date": "2024-07-15"},
    {"store_id": "STR-030", "name": f"{STORE_PREFIX} Rimini Marina",       "city": "Rimini",   "state": "Emilia-Romagna",       "neighborhood": "Marina Centro",      "sq_footage": 650, "seating_capacity": 14, "opened_date": "2024-03-15"},
    {"store_id": "STR-031", "name": f"{STORE_PREFIX} Perugia Centro",      "city": "Perugia",  "state": "Umbria",               "neighborhood": "Corso Vannucci",     "sq_footage": 600, "seating_capacity": 12, "opened_date": "2024-04-01"},
    {"store_id": "STR-032", "name": f"{STORE_PREFIX} Cagliari Marina",     "city": "Cagliari", "state": "Sardegna",             "neighborhood": "Marina",             "sq_footage": 580, "seating_capacity": 12, "opened_date": "2024-08-01"},
    {"store_id": "STR-033", "name": f"{STORE_PREFIX} Pisa Centro",         "city": "Pisa",     "state": "Toscana",              "neighborhood": "Borgo Stretto",      "sq_footage": 560, "seating_capacity": 12, "opened_date": "2023-11-15"},
    {"store_id": "STR-034", "name": f"{STORE_PREFIX} Roma Prati",          "city": "Roma",     "state": "Lazio",                "neighborhood": "Prati",              "sq_footage": 800, "seating_capacity": 20, "opened_date": "2024-09-15"},
    {"store_id": "STR-035", "name": f"{STORE_PREFIX} Como Lago",           "city": "Como",     "state": "Lombardia",            "neighborhood": "Lungolago",          "sq_footage": 620, "seating_capacity": 14, "opened_date": "2024-03-01"},
    {"store_id": "STR-036", "name": f"{STORE_PREFIX} Monza Centro",        "city": "Monza",    "state": "Lombardia",            "neighborhood": "Centro Storico",     "sq_footage": 600, "seating_capacity": 12, "opened_date": "2024-06-15"},
    {"store_id": "STR-037", "name": f"{STORE_PREFIX} Vicenza Centro",      "city": "Vicenza",  "state": "Veneto",               "neighborhood": "Corso Palladio",     "sq_footage": 660, "seating_capacity": 14, "opened_date": "2024-04-01"},
    {"store_id": "STR-038", "name": f"{STORE_PREFIX} Lecce Centro",        "city": "Lecce",    "state": "Puglia",               "neighborhood": "Centro Storico",     "sq_footage": 580, "seating_capacity": 12, "opened_date": "2024-10-15"},
    {"store_id": "STR-039", "name": f"{STORE_PREFIX} Salerno Lungomare",   "city": "Salerno",  "state": "Campania",             "neighborhood": "Lungomare",          "sq_footage": 640, "seating_capacity": 14, "opened_date": "2023-07-01"},
    {"store_id": "STR-040", "name": f"{STORE_PREFIX} Ancona Centro",       "city": "Ancona",   "state": "Marche",               "neighborhood": "Corso Garibaldi",    "sq_footage": 560, "seating_capacity": 12, "opened_date": "2024-11-15"},
    {"store_id": "STR-041", "name": f"{STORE_PREFIX} Bolzano Centro",      "city": "Bolzano",  "state": "Trentino-Alto Adige",  "neighborhood": "Via dei Portici",    "sq_footage": 540, "seating_capacity": 10, "opened_date": NEW_STORE_OPEN.strftime("%Y-%m-%d")},
    {"store_id": "STR-042", "name": f"{STORE_PREFIX} Pescara Centro",      "city": "Pescara",  "state": "Abruzzo",              "neighborhood": "Corso Umberto",      "sq_footage": 720, "seating_capacity": 16, "opened_date": "2023-05-15"},
]

stores_pdf = pd.DataFrame(stores_data)
store_ids = stores_pdf["store_id"].tolist()
print(f"  Created {len(stores_pdf)} stores")

# =============================================================================
# 2. PRODUCTS (Drinks Menu)
# =============================================================================
print("Generating products...")

products_data = [
    # Classici
    {"product_id": "PRD-001", "name": "Mortadella & Pistacchio",       "category": "Classici",    "base_price": 6.00, "cost": 1.90, "is_seasonal": False, "bread_base": "Michetta"},
    {"product_id": "PRD-002", "name": "Prosciutto Crudo & Mozzarella", "category": "Classici",    "base_price": 6.50, "cost": 2.10, "is_seasonal": False, "bread_base": "Ciabatta"},
    {"product_id": "PRD-003", "name": "Cotto e Funghi",                "category": "Classici",    "base_price": 5.50, "cost": 1.70, "is_seasonal": False, "bread_base": "Michetta"},
    {"product_id": "PRD-004", "name": "Salame & Pecorino",            "category": "Classici",    "base_price": 6.00, "cost": 1.95, "is_seasonal": False, "bread_base": "Pane Casereccio"},
    {"product_id": "PRD-005", "name": "Caprese",                       "category": "Classici",    "base_price": 5.50, "cost": 1.60, "is_seasonal": False, "bread_base": "Focaccia"},
    {"product_id": "PRD-006", "name": "Tonno e Cipolla",               "category": "Classici",    "base_price": 5.75, "cost": 1.65, "is_seasonal": False, "bread_base": "Michetta"},
    # Gourmet
    {"product_id": "PRD-007", "name": "Tartufo & Stracciatella",       "category": "Gourmet",     "base_price": 8.50, "cost": 3.10, "is_seasonal": False, "bread_base": "Pane ai Cereali"},
    {"product_id": "PRD-008", "name": "Culatello & Burrata",           "category": "Gourmet",     "base_price": 9.00, "cost": 3.40, "is_seasonal": False, "bread_base": "Ciabatta"},
    {"product_id": "PRD-009", "name": "'Nduja & Friarielli",           "category": "Gourmet",     "base_price": 7.50, "cost": 2.60, "is_seasonal": False, "bread_base": "Pane Casereccio"},
    {"product_id": "PRD-010", "name": "Porchetta di Ariccia",          "category": "Gourmet",     "base_price": 7.50, "cost": 2.50, "is_seasonal": False, "bread_base": "Ciabatta"},
    {"product_id": "PRD-011", "name": "Roast Beef & Rucola",           "category": "Gourmet",     "base_price": 8.00, "cost": 2.80, "is_seasonal": False, "bread_base": "Focaccia"},
    {"product_id": "PRD-012", "name": "Speck & Brie",                  "category": "Gourmet",     "base_price": 7.75, "cost": 2.70, "is_seasonal": False, "bread_base": "Pane ai Cereali"},
    # Vegetariani
    {"product_id": "PRD-013", "name": "Melanzane & Scamorza",          "category": "Vegetariani", "base_price": 6.00, "cost": 1.80, "is_seasonal": False, "bread_base": "Focaccia"},
    {"product_id": "PRD-014", "name": "Zucchine Grigliate & Hummus",   "category": "Vegetariani", "base_price": 6.00, "cost": 1.75, "is_seasonal": False, "bread_base": "Pane ai Cereali"},
    {"product_id": "PRD-015", "name": "Caprese Vegana",                "category": "Vegetariani", "base_price": 6.25, "cost": 1.85, "is_seasonal": False, "bread_base": "Focaccia"},
    {"product_id": "PRD-016", "name": "Friggitelli & Stracciatella",   "category": "Vegetariani", "base_price": 6.75, "cost": 2.10, "is_seasonal": False, "bread_base": "Pane Casereccio"},
    # Regionali
    {"product_id": "PRD-017", "name": "Lampredotto alla Fiorentina",   "category": "Regionali",   "base_price": 6.50, "cost": 2.00, "is_seasonal": False, "bread_base": "Panino Toscano"},
    {"product_id": "PRD-018", "name": "Pane e Panelle",                "category": "Regionali",   "base_price": 5.50, "cost": 1.40, "is_seasonal": False, "bread_base": "Mafalda"},
    {"product_id": "PRD-019", "name": "Piadina Romagnola",             "category": "Regionali",   "base_price": 6.00, "cost": 1.70, "is_seasonal": False, "bread_base": "Piadina"},
    {"product_id": "PRD-020", "name": "Puccia Salentina",              "category": "Regionali",   "base_price": 6.25, "cost": 1.80, "is_seasonal": False, "bread_base": "Puccia"},
    {"product_id": "PRD-021", "name": "Focaccia di Recco",             "category": "Regionali",   "base_price": 6.50, "cost": 1.90, "is_seasonal": False, "bread_base": "Focaccia di Recco"},
    # Stagionali
    {"product_id": "PRD-022", "name": "Zucca & Speck",                 "category": "Stagionali",  "base_price": 7.00, "cost": 2.30, "is_seasonal": True,  "bread_base": "Pane ai Cereali"},
    {"product_id": "PRD-023", "name": "Asparagi & Uovo",               "category": "Stagionali",  "base_price": 7.00, "cost": 2.20, "is_seasonal": True,  "bread_base": "Ciabatta"},
    {"product_id": "PRD-024", "name": "Caprese Estiva",                "category": "Stagionali",  "base_price": 6.75, "cost": 1.95, "is_seasonal": True,  "bread_base": "Focaccia"},
    {"product_id": "PRD-025", "name": "Tartufo Bianco d'Alba",         "category": "Stagionali",  "base_price": 9.50, "cost": 3.60, "is_seasonal": True,  "bread_base": "Pane Casereccio"},
    # Premium
    {"product_id": "PRD-026", "name": "Wagyu & Cipolla Caramellata",   "category": "Premium",     "base_price": 13.50,"cost": 5.50, "is_seasonal": False, "bread_base": "Pane Brioche"},
    {"product_id": "PRD-027", "name": "Baccalà Mantecato",             "category": "Premium",     "base_price": 10.00,"cost": 3.80, "is_seasonal": False, "bread_base": "Ciabatta"},
    {"product_id": "PRD-028", "name": "Vitello Tonnato",               "category": "Premium",     "base_price": 9.50, "cost": 3.40, "is_seasonal": False, "bread_base": "Pane Casereccio"},
    # Senza Glutine — certified gluten-free bread, prepared in a dedicated station to avoid cross-contamination
    {"product_id": "PRD-029", "name": "Senza Glutine - Crudo & Mozzarella", "category": "Senza Glutine", "base_price": 7.50, "cost": 2.40, "is_seasonal": False, "bread_base": "Pane Senza Glutine Certificato"},
]

products_pdf = pd.DataFrame(products_data)
product_ids = products_pdf["product_id"].tolist()

# Popularity weights - some drinks sell much more
product_popularity = {
    "PRD-001": 0.12, "PRD-002": 0.10, "PRD-003": 0.11, "PRD-004": 0.09, "PRD-005": 0.06,
    "PRD-006": 0.05, "PRD-007": 0.04, "PRD-008": 0.07, "PRD-009": 0.03, "PRD-010": 0.04,
    "PRD-011": 0.04, "PRD-012": 0.04, "PRD-013": 0.03, "PRD-014": 0.03, "PRD-015": 0.02,
    "PRD-016": 0.01, "PRD-017": 0.02, "PRD-018": 0.01, "PRD-019": 0.01, "PRD-020": 0.02,
    "PRD-021": 0.02, "PRD-022": 0.02, "PRD-023": 0.01, "PRD-024": 0.03, "PRD-025": 0.02,
    "PRD-026": 0.02, "PRD-027": 0.02, "PRD-028": 0.01, "PRD-029": 0.02,
}
product_weights = np.array([product_popularity[p] for p in product_ids])
product_weights = (product_weights / product_weights.sum()).tolist()
print(f"  Created {len(products_pdf)} products")

# =============================================================================
# 3. TOPPINGS
# =============================================================================
print("Generating toppings...")

toppings_data = [
    {"topping_id": "TOP-001", "name": "Doppia Mozzarella",   "price": 1.50, "cost": 0.45, "is_available": True},
    {"topping_id": "TOP-002", "name": "'Nduja Piccante",     "price": 1.00, "cost": 0.30, "is_available": True},
    {"topping_id": "TOP-003", "name": "Stracciatella",       "price": 1.50, "cost": 0.50, "is_available": True},
    {"topping_id": "TOP-004", "name": "Friarielli",          "price": 1.00, "cost": 0.28, "is_available": True},
    {"topping_id": "TOP-005", "name": "Funghi Trifolati",    "price": 1.00, "cost": 0.26, "is_available": True},
    {"topping_id": "TOP-006", "name": "Rucola",              "price": 0.50, "cost": 0.12, "is_available": True},
    {"topping_id": "TOP-007", "name": "Pomodori Secchi",     "price": 1.00, "cost": 0.30, "is_available": True},
    {"topping_id": "TOP-008", "name": "Melanzane Grigliate", "price": 1.00, "cost": 0.25, "is_available": True},
    {"topping_id": "TOP-009", "name": "Salsa Tartufata",     "price": 2.00, "cost": 0.70, "is_available": True},
    {"topping_id": "TOP-010", "name": "Pesto Genovese",      "price": 0.75, "cost": 0.22, "is_available": True},
    {"topping_id": "TOP-011", "name": "Burrata",             "price": 2.00, "cost": 0.75, "is_available": True},
    {"topping_id": "TOP-012", "name": "Cipolla Caramellata", "price": 0.75, "cost": 0.18, "is_available": True},
]

toppings_pdf = pd.DataFrame(toppings_data)
topping_ids = toppings_pdf["topping_id"].tolist()

# Doppia Mozzarella dominates - ~35% of extra additions (first weight maps to TOP-001)
topping_weights = np.array([0.35, 0.08, 0.07, 0.09, 0.06, 0.05, 0.04, 0.05, 0.06, 0.04, 0.07, 0.04])
topping_weights = (topping_weights / topping_weights.sum()).tolist()
print(f"  Created {len(toppings_pdf)} toppings")

# =============================================================================
# 4. SUPPLIERS
# =============================================================================
print("Generating suppliers...")

suppliers_data = [
    {"supplier_id": "SUP-001", "name": "Salumificio Emiliano S.r.l.",  "country": "Italy", "category": "Salumi",                "lead_time_days": 4,  "reliability_score": 4.8},
    {"supplier_id": "SUP-002", "name": "Caseificio del Sud",           "country": "Italy", "category": "Formaggi & Latticini",  "lead_time_days": 2,  "reliability_score": 4.9},
    {"supplier_id": "SUP-003", "name": "Forno Artigiano Milano",       "country": "Italy", "category": "Pane & Focacce",        "lead_time_days": 1,  "reliability_score": 4.7},
    {"supplier_id": "SUP-004", "name": "Ortofrutta Fresca S.p.A.",     "country": "Italy", "category": "Verdure & Ortaggi",     "lead_time_days": 2,  "reliability_score": 4.4},
    {"supplier_id": "SUP-005", "name": "Tartufi & Specialità Alba",    "country": "Italy", "category": "Specialità & Tartufi",  "lead_time_days": 6,  "reliability_score": 4.9},
    {"supplier_id": "SUP-006", "name": "Salse & Condimenti Italia",    "country": "Italy", "category": "Salse & Condimenti",    "lead_time_days": 3,  "reliability_score": 4.6},
    {"supplier_id": "SUP-007", "name": "EcoPack Imballaggi",           "country": "Italy", "category": "Packaging",             "lead_time_days": 7,  "reliability_score": 4.4},
    {"supplier_id": "SUP-008", "name": "Conserve Mediterranee",        "country": "Italy", "category": "Conserve & Ittico",     "lead_time_days": 5,  "reliability_score": 4.5},
]

suppliers_pdf = pd.DataFrame(suppliers_data)
supplier_ids = suppliers_pdf["supplier_id"].tolist()
print(f"  Created {len(suppliers_pdf)} suppliers")

# =============================================================================
# 5. INGREDIENTS
# =============================================================================
print("Generating ingredients...")

ingredients_data = [
    {"ingredient_id": "ING-001", "name": "Mortadella IGP",        "unit": "kg",    "unit_cost": 12.00, "supplier_id": "SUP-001", "reorder_threshold": 10.0},
    {"ingredient_id": "ING-002", "name": "Prosciutto Crudo",      "unit": "kg",    "unit_cost": 28.00, "supplier_id": "SUP-001", "reorder_threshold": 8.0},
    {"ingredient_id": "ING-003", "name": "Salame Milano",         "unit": "kg",    "unit_cost": 16.00, "supplier_id": "SUP-001", "reorder_threshold": 6.0},
    {"ingredient_id": "ING-004", "name": "Speck Alto Adige",      "unit": "kg",    "unit_cost": 22.00, "supplier_id": "SUP-001", "reorder_threshold": 5.0},
    {"ingredient_id": "ING-005", "name": "Culatello di Zibello",  "unit": "kg",    "unit_cost": 45.00, "supplier_id": "SUP-001", "reorder_threshold": 3.0},
    {"ingredient_id": "ING-006", "name": "Mozzarella Fiordilatte","unit": "kg",    "unit_cost": 8.50,  "supplier_id": "SUP-002", "reorder_threshold": 20.0},
    {"ingredient_id": "ING-007", "name": "Pecorino Romano",       "unit": "kg",    "unit_cost": 18.00, "supplier_id": "SUP-002", "reorder_threshold": 8.0},
    {"ingredient_id": "ING-008", "name": "Stracciatella di Bufala","unit": "kg",   "unit_cost": 14.00, "supplier_id": "SUP-002", "reorder_threshold": 6.0},
    {"ingredient_id": "ING-009", "name": "Burrata Pugliese",      "unit": "kg",    "unit_cost": 13.00, "supplier_id": "SUP-002", "reorder_threshold": 6.0},
    {"ingredient_id": "ING-010", "name": "Michette (pane)",       "unit": "case",  "unit_cost": 18.00, "supplier_id": "SUP-003", "reorder_threshold": 30.0},
    {"ingredient_id": "ING-011", "name": "Focaccia Genovese",     "unit": "case",  "unit_cost": 22.00, "supplier_id": "SUP-003", "reorder_threshold": 20.0},
    {"ingredient_id": "ING-012", "name": "Ciabatta",              "unit": "case",  "unit_cost": 20.00, "supplier_id": "SUP-003", "reorder_threshold": 20.0},
    {"ingredient_id": "ING-013", "name": "Friarielli",            "unit": "kg",    "unit_cost": 6.50,  "supplier_id": "SUP-004", "reorder_threshold": 10.0},
    {"ingredient_id": "ING-014", "name": "Rucola",                "unit": "kg",    "unit_cost": 5.00,  "supplier_id": "SUP-004", "reorder_threshold": 8.0},
    {"ingredient_id": "ING-015", "name": "Melanzane",             "unit": "kg",    "unit_cost": 3.50,  "supplier_id": "SUP-004", "reorder_threshold": 10.0},
    {"ingredient_id": "ING-016", "name": "Funghi Champignon",     "unit": "kg",    "unit_cost": 7.00,  "supplier_id": "SUP-004", "reorder_threshold": 8.0},
    {"ingredient_id": "ING-017", "name": "Tartufo Nero",          "unit": "kg",    "unit_cost": 280.00,"supplier_id": "SUP-005", "reorder_threshold": 1.0},
    {"ingredient_id": "ING-018", "name": "Pistacchio di Bronte",  "unit": "kg",    "unit_cost": 60.00, "supplier_id": "SUP-005", "reorder_threshold": 2.0},
    {"ingredient_id": "ING-019", "name": "Maionese",              "unit": "liter", "unit_cost": 4.50,  "supplier_id": "SUP-006", "reorder_threshold": 15.0},
    {"ingredient_id": "ING-020", "name": "Pesto Genovese",        "unit": "kg",    "unit_cost": 12.00, "supplier_id": "SUP-006", "reorder_threshold": 6.0},
    {"ingredient_id": "ING-021", "name": "Carta Alimentare",      "unit": "case",  "unit_cost": 35.00, "supplier_id": "SUP-007", "reorder_threshold": 5.0},
    {"ingredient_id": "ING-022", "name": "Tonno sott'olio",       "unit": "kg",    "unit_cost": 14.00, "supplier_id": "SUP-008", "reorder_threshold": 10.0},
]

ingredients_pdf = pd.DataFrame(ingredients_data)
ingredient_ids = ingredients_pdf["ingredient_id"].tolist()
print(f"  Created {len(ingredients_pdf)} ingredients")

# =============================================================================
# 6. PROMOTIONS
# =============================================================================
print("Generating promotions...")

promotions_data = [
    {"promotion_id": "PRM-001", "name": "Grande Apertura - Bolzano",    "type": "BOGO",           "discount_pct": 50.0, "min_order": 0.00, "start_date": NEW_STORE_OPEN.strftime("%Y-%m-%d"),                          "end_date": (NEW_STORE_OPEN + timedelta(days=14)).strftime("%Y-%m-%d"), "store_id": "STR-041"},
    {"promotion_id": "PRM-002", "name": "Promo Caprese Estiva",         "type": "DISCOUNT",        "discount_pct": 15.0, "min_order": 0.00, "start_date": MANGO_PROMO_START.strftime("%Y-%m-%d"),                      "end_date": MANGO_PROMO_END.strftime("%Y-%m-%d"),                      "store_id": None},
    {"promotion_id": "PRM-003", "name": "Aperitivo (17-19)",            "type": "HAPPY_HOUR",      "discount_pct": 20.0, "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-004", "name": "Punti Fedeltà Doppi",          "type": "LOYALTY",         "discount_pct": 0.0,  "min_order": 15.00,"start_date": (START_DATE + timedelta(days=30)).strftime("%Y-%m-%d"),     "end_date": (START_DATE + timedelta(days=44)).strftime("%Y-%m-%d"),   "store_id": None},
    {"promotion_id": "PRM-005", "name": "Venerdì Extra Gratis",         "type": "FREE_ITEM",       "discount_pct": 0.0,  "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-006", "name": "Sconto Studenti",              "type": "DISCOUNT",        "discount_pct": 10.0, "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-007", "name": "Speciale Compleanno",          "type": "BIRTHDAY",        "discount_pct": 25.0, "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-008", "name": "Porta un Amico",               "type": "REFERRAL",        "discount_pct": 15.0, "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-009", "name": "Benvenuto Nuovo Cliente",      "type": "DISCOUNT",        "discount_pct": 20.0, "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-010", "name": "Speciale Autunno Zucca",       "type": "SEASONAL",        "discount_pct": 10.0, "min_order": 0.00, "start_date": (END_DATE - timedelta(days=60)).strftime("%Y-%m-%d"),       "end_date": (END_DATE - timedelta(days=30)).strftime("%Y-%m-%d"),     "store_id": None},
    {"promotion_id": "PRM-011", "name": "Lunedì del Tartufo",           "type": "DAY_OF_WEEK",     "discount_pct": 15.0, "min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-012", "name": "Prendi 5 Paghi 4",             "type": "LOYALTY_PUNCH",   "discount_pct": 100.0,"min_order": 0.00, "start_date": START_DATE.strftime("%Y-%m-%d"),                             "end_date": END_DATE.strftime("%Y-%m-%d"),                             "store_id": None},
    {"promotion_id": "PRM-013", "name": "Upgrade Pane Speciale Gratis", "type": "FREE_UPGRADE",    "discount_pct": 0.0,  "min_order": 0.00, "start_date": (START_DATE + timedelta(days=60)).strftime("%Y-%m-%d"),     "end_date": (START_DATE + timedelta(days=74)).strftime("%Y-%m-%d"),   "store_id": None},
    {"promotion_id": "PRM-014", "name": "Speciale San Valentino",       "type": "HOLIDAY",         "discount_pct": 15.0, "min_order": 20.00,"start_date": (START_DATE + timedelta(days=45)).strftime("%Y-%m-%d"),     "end_date": (START_DATE + timedelta(days=47)).strftime("%Y-%m-%d"),   "store_id": None},
    {"promotion_id": "PRM-015", "name": "Promo Lancio App",             "type": "APP_EXCLUSIVE",   "discount_pct": 25.0, "min_order": 0.00, "start_date": (START_DATE + timedelta(days=10)).strftime("%Y-%m-%d"),     "end_date": (START_DATE + timedelta(days=24)).strftime("%Y-%m-%d"),   "store_id": None},
]

promotions_pdf = pd.DataFrame(promotions_data)
promotion_ids = promotions_pdf["promotion_id"].tolist()
print(f"  Created {len(promotions_pdf)} promotions")

# =============================================================================
# 7. CUSTOMERS
# =============================================================================
print("Generating customers...")

loyalty_tiers = np.random.choice(["Bronze", "Silver", "Gold", "Platinum"], N_CUSTOMERS, p=[0.55, 0.28, 0.12, 0.05])
preferred_bread = np.random.choice(["Michetta", "Ciabatta", "Focaccia", "Pane ai Cereali", "Piadina"], N_CUSTOMERS, p=[0.35, 0.25, 0.18, 0.12, 0.10])
# Weight home_store by store age (older stores have more established customer bases)
_store_age_days = [(END_DATE - datetime.strptime(s["opened_date"], "%Y-%m-%d")).days for s in stores_data]
_home_store_weights = np.array([max(d, 30) for d in _store_age_days], dtype=float)
_home_store_weights /= _home_store_weights.sum()
home_store = np.random.choice(store_ids, N_CUSTOMERS, p=_home_store_weights)

# Loyalty points correlate with tier
tier_points_map = {"Bronze": (50, 200), "Silver": (200, 800), "Gold": (800, 2500), "Platinum": (2500, 8000)}
loyalty_points = [int(np.random.uniform(*tier_points_map[t])) for t in loyalty_tiers]

customers_pdf = pd.DataFrame({
    "customer_id": [f"CUST-{i:05d}" for i in range(N_CUSTOMERS)],
    "first_name": [fake.first_name() for _ in range(N_CUSTOMERS)],
    "last_name": [fake.last_name() for _ in range(N_CUSTOMERS)],
    "email": [fake.email() for _ in range(N_CUSTOMERS)],
    "loyalty_tier": loyalty_tiers,
    "loyalty_points": loyalty_points,
    "preferred_bread": preferred_bread,
    "home_store_id": home_store,
    "joined_date": [fake.date_between(start_date="-3y", end_date=START_DATE) for _ in range(N_CUSTOMERS)],
    "birth_month": np.random.randint(1, 13, N_CUSTOMERS),
    "is_student": np.random.choice([True, False], N_CUSTOMERS, p=[0.22, 0.78]),
    "app_user": np.random.choice([True, False], N_CUSTOMERS, p=[0.60, 0.40]),
})

# Convert date objects to strings for clean Parquet serialization
customers_pdf["joined_date"] = customers_pdf["joined_date"].astype(str)

customer_ids = customers_pdf["customer_id"].tolist()
customer_tier_map = dict(zip(customers_pdf["customer_id"], customers_pdf["loyalty_tier"]))
customer_store_map = dict(zip(customers_pdf["customer_id"], customers_pdf["home_store_id"]))

# Higher tier customers order more frequently
tier_visit_weight = customers_pdf["loyalty_tier"].map({"Platinum": 6.0, "Gold": 3.5, "Silver": 2.0, "Bronze": 1.0})
customer_weights = (tier_visit_weight / tier_visit_weight.sum()).tolist()

print(f"  Created {len(customers_pdf):,} customers")

# =============================================================================
# 8. ORDERS + ORDER ITEMS + ORDER ITEM TOPPINGS
# =============================================================================
print("Generating orders, order_items, order_item_toppings...")

sizes = ["Junior", "Classico", "Maxi"]
size_weights = [0.20, 0.55, 0.25]
size_price_add = {"Junior": -1.00, "Classico": 0.00, "Maxi": 1.50}

bread_types = ["Michetta", "Ciabatta", "Focaccia", "Pane ai Cereali", "Piadina", "Pane Casereccio"]
bread_weights = [0.30, 0.20, 0.18, 0.12, 0.10, 0.10]

toasting_options = ["Tostato", "Non Tostato", "Caldo alla Piastra", "Freddo"]
toasting_weights = [0.45, 0.30, 0.15, 0.10]

sauce_options = ["Nessuna", "Maionese", "Senape", "Salsa Tartufata", "Pesto"]
sauce_weights = [0.40, 0.25, 0.14, 0.11, 0.10]
sauce_upcharge = {"Nessuna": 0.00, "Maionese": 0.00, "Senape": 0.00, "Salsa Tartufata": 1.50, "Pesto": 0.50}

channels = ["In-Store", "Mobile App", "Online"]
channel_weights = [0.55, 0.35, 0.10]

# Build a lookup from store_id -> opened_date for new-store logic
_store_opened = {s["store_id"]: datetime.strptime(s["opened_date"], "%Y-%m-%d") for s in stores_data}


# Volume multiplier per day
def get_daily_multiplier(date, store_id):
    meta = STORE_META[store_id]
    m = 1.0

    # Weekend boost for panino shops
    if date.weekday() >= 5:
        m *= 1.35

    # Holiday drop - Italian national holidays
    country_hols = COUNTRY_HOLIDAYS.get(meta["holiday_key"])
    if country_hols and date in country_hols:
        m *= 0.50

    # Seasonal adjustment (hemisphere-aware)
    month = date.month
    if meta["hemisphere"] == "S":
        # Southern hemisphere: warm months are Dec-Feb, cool months are Jun-Aug
        if month in [12, 1, 2]:
            m *= 1.20
        elif month in [6, 7, 8]:
            m *= 0.85
    else:
        # Northern hemisphere: warm months are Jun-Aug, cool months are Dec-Feb
        if month in [6, 7, 8]:
            m *= 1.20
        elif month in [12, 1, 2]:
            m *= 0.85

    # New store opening spike - works for any store that opened within the data window
    opened = _store_opened[store_id]
    days_open = (date - opened).days
    if days_open < 0:
        return 0.0
    elif days_open < 14:
        m *= 2.5
    elif days_open < 30:
        m *= 1.5

    # Mango promo lift
    if MANGO_PROMO_START <= date <= MANGO_PROMO_END:
        m *= 1.15

    return max(0.1, m * np.random.normal(1, 0.12))

from tqdm import tqdm as _tqdm

orders_data = []
order_items_data = []
order_item_toppings_data = []

order_idx = 0
item_idx = 0
topping_idx = 0

# Pre-build lookup dicts to avoid per-item DataFrame scans inside the loop
product_price_map = dict(zip(products_pdf["product_id"], products_pdf["base_price"]))
topping_price_map = dict(zip(toppings_pdf["topping_id"],  toppings_pdf["price"]))

# Pre-normalise hour probabilities once (identical for every order)
_hour_probs_raw = [0.01]*8 + [0.03, 0.05, 0.06, 0.05, 0.08, 0.10, 0.08, 0.10, 0.12, 0.10, 0.08, 0.07, 0.05, 0.03, 0.02, 0.01]
_hour_probs     = [p / sum(_hour_probs_raw) for p in _hour_probs_raw]

_pbar = _tqdm(total=N_ORDERS, desc="Generating orders", unit="order")
# Generate orders distributed across dates and stores
# Derive base volume from store age: flagships (2+ yr) get 45-60, newer get less
store_base_volume = {}
for s in stores_data:
    opened = datetime.strptime(s["opened_date"], "%Y-%m-%d")
    age_days = (END_DATE - opened).days
    if age_days > 730:        # 2+ years: flagship
        base = int(45 + (age_days - 730) / 365 * 10)
        base = min(base, 60)
    elif age_days > 365:      # 1-2 years: established
        base = int(30 + (age_days - 365) / 365 * 15)
    elif age_days > 180:      # 6-12 months: growing
        base = int(20 + (age_days - 180) / 185 * 10)
    elif age_days > 60:       # 2-6 months: ramping
        base = int(12 + (age_days - 60) / 120 * 8)
    else:                      # <2 months: new
        base = 10
    store_base_volume[s["store_id"]] = max(1, round(base * N_ORDERS / 200_000))

for day in pd.date_range(START_DATE, END_DATE):
    day_dt = day.to_pydatetime()
    day_str = day.strftime("%Y-%m-%d")
    is_weekend = day_dt.weekday() >= 5

    for store_id in store_ids:
        base = store_base_volume[store_id]
        multiplier = get_daily_multiplier(day_dt, store_id)
        n_orders_today = int(base * multiplier)

        for _ in range(n_orders_today):
            if order_idx >= N_ORDERS:
                break

            cid = np.random.choice(customer_ids, p=customer_weights)
            tier = customer_tier_map[cid]
            channel = np.random.choice(channels, p=channel_weights)

            # Order time - peaks at lunch and after work
            # Hours 0-7 are low traffic, 8-23 ramp up with lunch/afternoon peaks
            hour = np.random.choice(range(24), p=_hour_probs)
            minute = np.random.randint(0, 60)
            order_time = f"{hour:02d}:{minute:02d}"

            # Number of items in order
            n_items = np.random.choice([1, 2, 3, 4], p=[0.55, 0.30, 0.12, 0.03])

            order_subtotal = 0.0
            order_item_ids = []

            for j in range(n_items):
                product_id = np.random.choice(product_ids, p=product_weights)
                size = np.random.choice(sizes, p=size_weights)
                bread = np.random.choice(bread_types, p=bread_weights)
                toasting = np.random.choice(toasting_options, p=toasting_weights)
                sauce = np.random.choice(sauce_options, p=sauce_weights)

                item_price = round(product_price_map[product_id] + size_price_add[size] + sauce_upcharge[sauce], 2)
                order_subtotal += item_price

                item_id = f"ITM-{item_idx:07d}"
                order_item_ids.append(item_id)

                order_items_data.append({
                    "order_item_id": item_id,
                    "order_id": f"ORD-{order_idx:07d}",
                    "product_id": product_id,
                    "size": size,
                    "bread_type": bread,
                    "toasting": toasting,
                    "sauce": sauce,
                    "item_price": item_price,
                })
                item_idx += 1

                # Toppings - ~65% chance of at least one topping
                n_toppings = np.random.choice([0, 1, 2, 3], p=[0.35, 0.42, 0.18, 0.05])
                selected_toppings = np.random.choice(topping_ids, size=min(n_toppings, len(topping_ids)), replace=False, p=topping_weights) if n_toppings > 0 else []

                for top_id in selected_toppings:
                    top_price = topping_price_map[top_id]
                    order_subtotal += top_price
                    order_item_toppings_data.append({
                        "order_item_topping_id": f"OIT-{topping_idx:07d}",
                        "order_item_id": item_id,
                        "topping_id": top_id,
                        "price": top_price,
                    })
                    topping_idx += 1

            # Apply promotion discount
            promo_id = None
            discount = 0.0
            active_promos = [
                p for p in promotions_data
                if p["start_date"] <= day_str <= p["end_date"]
                and (p["store_id"] is None or p["store_id"] == store_id)
                and order_subtotal >= p["min_order"]
            ]
            if active_promos and np.random.random() < 0.18:
                promo = np.random.choice(active_promos)
                promo_id = promo["promotion_id"]
                if promo["discount_pct"] > 0:
                    discount = round(order_subtotal * promo["discount_pct"] / 100, 2)

            order_total = round(max(0, order_subtotal - discount), 2)
            tax = round(order_total * STORE_META[store_id]["tax_rate"], 2)

            orders_data.append({
                "order_id": f"ORD-{order_idx:07d}",
                "customer_id": cid,
                "store_id": store_id,
                "order_date": day_str,
                "order_time": order_time,
                "channel": channel,
                "subtotal": round(order_subtotal, 2),
                "discount": discount,
                "order_total": order_total,
                "tax": tax,
                "promotion_id": promo_id,
                "status": np.random.choice(["completed", "completed", "completed", "refunded"], p=[0.97, 0.01, 0.01, 0.01]),
            })
            order_idx += 1
            _pbar.update(1)

        if order_idx >= N_ORDERS:
            break
    if order_idx >= N_ORDERS:
        break
_pbar.close()

orders_pdf = pd.DataFrame(orders_data)
order_items_pdf = pd.DataFrame(order_items_data)
order_item_toppings_pdf = pd.DataFrame(order_item_toppings_data)

print(f"  Created {len(orders_pdf):,} orders")
print(f"  Created {len(order_items_pdf):,} order items")
print(f"  Created {len(order_item_toppings_pdf):,} order item toppings")

# =============================================================================
# 9. PURCHASE ORDERS (Supplier Orders)
# =============================================================================
print("Generating purchase orders...")

po_data = []
for i in range(2000):
    supplier_id = np.random.choice(supplier_ids)
    supplier = suppliers_pdf[suppliers_pdf["supplier_id"] == supplier_id].iloc[0]
    store_id = np.random.choice(store_ids)
    order_date = fake.date_between(start_date=START_DATE, end_date=END_DATE)
    lead_time = int(supplier["lead_time_days"] * np.random.normal(1, 0.15))
    delivery_date = order_date + timedelta(days=max(1, lead_time))
    amount = round(np.random.lognormal(5.8, 0.6), 2)

    po_data.append({
        "po_id": f"PO-{i:05d}",
        "supplier_id": supplier_id,
        "store_id": store_id,
        "order_date": order_date.strftime("%Y-%m-%d"),
        "expected_delivery_date": delivery_date.strftime("%Y-%m-%d"),
        "actual_delivery_date": (delivery_date + timedelta(days=int(np.random.choice([0, 0, 0, 1, 2, -1], p=[0.55, 0.15, 0.10, 0.10, 0.05, 0.05])))).strftime("%Y-%m-%d"),
        "total_amount": amount,
        "status": np.random.choice(["delivered", "delivered", "delivered", "pending", "cancelled"], p=[0.82, 0.05, 0.05, 0.07, 0.01]),
    })

purchase_orders_pdf = pd.DataFrame(po_data)
print(f"  Created {len(purchase_orders_pdf):,} purchase orders")

# =============================================================================
# 10. INVENTORY TRANSACTIONS
# =============================================================================
print("Generating inventory transactions...")

inv_data = []
for i in range(30000):
    store_id = np.random.choice(store_ids)
    ingredient_id = np.random.choice(ingredient_ids)
    txn_date = fake.date_between(start_date=START_DATE, end_date=END_DATE)
    txn_type = np.random.choice(["usage", "purchase", "waste", "adjustment"], p=[0.70, 0.22, 0.06, 0.02])
    quantity = round(np.random.lognormal(1.5, 0.8), 2) * (-1 if txn_type in ["usage", "waste"] else 1)

    inv_data.append({
        "transaction_id": f"INV-{i:06d}",
        "store_id": store_id,
        "ingredient_id": ingredient_id,
        "transaction_date": txn_date.strftime("%Y-%m-%d"),
        "transaction_type": txn_type,
        "quantity": quantity,
        "unit_cost": ingredients_pdf[ingredients_pdf["ingredient_id"] == ingredient_id]["unit_cost"].values[0],
    })

inventory_transactions_pdf = pd.DataFrame(inv_data)
print(f"  Created {len(inventory_transactions_pdf):,} inventory transactions")

# =============================================================================
# 11. PROMOTION REDEMPTIONS
# =============================================================================
print("Generating promotion redemptions...")

# Extract orders that had a promotion applied
promo_orders = orders_pdf[orders_pdf["promotion_id"].notna()][["order_id", "customer_id", "store_id", "order_date", "promotion_id", "discount"]]

redemptions_data = []
for i, row in enumerate(promo_orders.itertuples()):
    redemptions_data.append({
        "redemption_id": f"RDM-{i:06d}",
        "promotion_id": row.promotion_id,
        "order_id": row.order_id,
        "customer_id": row.customer_id,
        "store_id": row.store_id,
        "redemption_date": row.order_date,
        "discount_applied": row.discount,
    })

promotion_redemptions_pdf = pd.DataFrame(redemptions_data)
print(f"  Created {len(promotion_redemptions_pdf):,} promotion redemptions")

# =============================================================================
# 12. UPLOAD & CREATE DELTA TABLES
# =============================================================================
print(f"\nUploading data and creating Delta tables in {CATALOG}.{SCHEMA}...")

tables = {
    "stores": stores_pdf,
    "products": products_pdf,
    "toppings": toppings_pdf,
    "ingredients": ingredients_pdf,
    "suppliers": suppliers_pdf,
    "promotions": promotions_pdf,
    "customers": customers_pdf,
    "orders": orders_pdf,
    "order_items": order_items_pdf,
    "order_item_toppings": order_item_toppings_pdf,
    "purchase_orders": purchase_orders_pdf,
    "inventory_transactions": inventory_transactions_pdf,
    "promotion_redemptions": promotion_redemptions_pdf,
}

for table_name, df in tables.items():
    upload_and_create_table(table_name, df)
    print(f"  Saved {table_name}: {len(df):,} rows")

# =============================================================================
# 13. VALIDATION SUMMARY
# =============================================================================
print("\n=== VALIDATION SUMMARY ===")
print(f"Date range: {START_DATE.strftime('%Y-%m-%d')} to {END_DATE.strftime('%Y-%m-%d')}")
print(f"Total orders: {len(orders_pdf):,}")
print(f"Total revenue: ${orders_pdf['order_total'].sum():,.2f}")
print(f"Avg order value: ${orders_pdf['order_total'].mean():.2f}")
print(f"Orders by channel:\n{orders_pdf['channel'].value_counts().to_string()}")
print(f"Orders by store:\n{orders_pdf['store_id'].value_counts().to_string()}")
print(f"Loyalty tier distribution:\n{customers_pdf['loyalty_tier'].value_counts().to_string()}")
promo_rate = orders_pdf["promotion_id"].notna().mean() * 100
print(f"Promotion redemption rate: {promo_rate:.1f}%")

# Remote verification
print("\n=== REMOTE VERIFICATION ===")
for table_name in tables.keys():
    resp = run_sql(f"SELECT COUNT(*) as cnt FROM {CATALOG}.{SCHEMA}.{table_name}")
    count = resp.result.data_array[0][0] if resp.result and resp.result.data_array else "?"
    print(f"  {table_name}: {count} rows")

print("\nAll tables saved successfully!")
