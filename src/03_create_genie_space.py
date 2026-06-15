"""Step 03 - Author + create the Panino Bricks Genie space.

Builds a serialized Genie space (tables, instructions, example SQL) with the vibe
`genie-rooms` skill helper (GenieSpaceBuilder), then creates it via REST:
  databricks api post /api/2.0/genie/spaces --json @<payload>

Captures and prints the created GENIE_SPACE_ID (the orchestrator reads it).

PATCH/serialization rules baked in (learned the hard way):
  - text_instructions must have AT MOST ONE item.
  - id-bearing lists (example_question_sqls, benchmarks, benchmarks.questions)
    must be sorted by their uuid `id`.
  - benchmark answer `format` must be "SQL".

Requires the `genie-rooms` skill resources on the path. Set GENIE_BUILDER_PATH
if the cached default below does not match your install.

Run standalone:
  python src/03_create_genie_space.py --profile <ws> --catalog <cat> --warehouse-id <wh>
"""
import os
import sys
import json
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

parser = argparse.ArgumentParser(description="Create Panino Bricks Genie space")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit in-workspace)")
parser.add_argument("--catalog", default=None, help="Override PB_CATALOG")
parser.add_argument("--schema", default=None, help="Override PB_SCHEMA")
parser.add_argument("--warehouse-id", default=None, help="SQL warehouse ID (auto-discovered if omitted)")
parser.add_argument("--parent-path", default=None,
                    help="Workspace folder for the space (default: /Workspace/Users/<me>)")
parser.add_argument("--out", default="/tmp/pb_create_genie_space.json",
                    help="Where to write the create payload")
args = parser.parse_args()

if args.catalog:
    os.environ["PB_CATALOG"] = args.catalog
if args.schema:
    os.environ["PB_SCHEMA"] = args.schema

from config import CATALOG, SCHEMA, GENIE_SPACE_TITLE  # noqa: E402
from _common import get_workspace_client, discover_warehouse_id, databricks_api  # noqa: E402

# Locate the genie-rooms skill helper.
_DEFAULT_BUILDER = os.path.expanduser(
    "~/.claude/plugins/cache/fe-vibe/fe-internal-tools/1.4.0/skills/genie-rooms/resources"
)
sys.path.insert(0, os.environ.get("GENIE_BUILDER_PATH", _DEFAULT_BUILDER))
try:
    from genie_space_builder import GenieSpaceBuilder  # noqa: E402
except Exception as exc:  # pragma: no cover - only at runtime without the skill
    sys.exit(
        "Could not import genie_space_builder. Install/enable the vibe `genie-rooms` "
        "skill and/or set GENIE_BUILDER_PATH to its resources dir.\n"
        f"Original error: {exc}"
    )

w = get_workspace_client(args.profile)
WH = discover_warehouse_id(w, args.warehouse_id or os.environ.get("PB_WAREHOUSE_ID"))
parent_path = args.parent_path or f"/Workspace/Users/{w.current_user.me().user_name}"

CAT, SCH = CATALOG, SCHEMA

space = GenieSpaceBuilder(
    title=GENIE_SPACE_TITLE,
    description="Analisi vendite, scorte, clienti e promozioni della catena italiana di paninoteche Panino Bricks.",
    warehouse_id=WH,
)

space.set_instructions(
    "Panino Bricks e' una catena italiana di paninoteche con punti vendita in Italia. "
    "Rispondi SEMPRE in italiano. Tutti gli importi monetari sono in euro (EUR). "
    "Tabelle principali: "
    "`orders` = scontrini/ordini (order_total include lo sconto applicato; tax = IVA 10%; channel = canale di vendita: 'In-Store', 'Mobile App', 'Online'). "
    "`order_items` = singoli panini per ordine (size = taglia Junior/Classico/Maxi, bread_type = pane, toasting = tostatura, sauce = salsa). "
    "`order_item_toppings` = extra/aggiunte per panino. "
    "`products` = i panini (category: Classici, Gourmet, Vegetariani, Regionali, Stagionali, Premium, Senza Glutine). "
    "`toppings` = extra (es. doppia mozzarella, 'nduja, stracciatella). "
    "`ingredients` + `suppliers` = ingredienti e fornitori (reorder_threshold = soglia di riordino). "
    "`stores` = punti vendita (city, neighborhood, state=regione). "
    "`customers` = clienti (loyalty_tier: Bronze/Silver/Gold/Platinum). "
    "`promotions` + `promotion_redemptions` = promozioni e riscatti. "
    "`inventory_transactions` = movimenti di magazzino (transaction_type: usage/purchase/waste/adjustment). "
    "`purchase_orders` = ordini ai fornitori. "
    "Per 'fatturato' o 'vendite' usa SUM(orders.order_total). Per 'scontrino medio' usa AVG(orders.order_total). "
    "Per il panino piu' venduto conta le righe in order_items unite a products. "
    "Le scorte basse si valutano da inventory_transactions aggregate per ingrediente/store rispetto a ingredients.reorder_threshold."
)

for t in ["stores", "products", "toppings", "ingredients", "suppliers", "promotions",
          "customers", "orders", "order_items", "order_item_toppings",
          "purchase_orders", "inventory_transactions", "promotion_redemptions"]:
    space.add_table(f"{CAT}.{SCH}.{t}")

space.add_example_sql(
    title="Top 10 panini piu' venduti per pezzi",
    sql=(
        f"SELECT p.name AS panino, p.category AS categoria, COUNT(*) AS pezzi_venduti "
        f"FROM {CAT}.{SCH}.order_items oi "
        f"JOIN {CAT}.{SCH}.products p ON oi.product_id = p.product_id "
        f"GROUP BY p.name, p.category ORDER BY pezzi_venduti DESC LIMIT 10"
    ),
)
space.add_example_sql(
    title="Fatturato per punto vendita",
    sql=(
        f"SELECT s.name AS punto_vendita, s.city AS citta, ROUND(SUM(o.order_total),2) AS fatturato_eur "
        f"FROM {CAT}.{SCH}.orders o "
        f"JOIN {CAT}.{SCH}.stores s ON o.store_id = s.store_id "
        f"GROUP BY s.name, s.city ORDER BY fatturato_eur DESC"
    ),
)
space.add_example_sql(
    title="Costo degli sprechi per ingrediente e punto vendita",
    sql=(
        f"SELECT i.name AS ingrediente, s.name AS punto_vendita, "
        f"ROUND(SUM(ABS(it.quantity) * it.unit_cost), 2) AS costo_spreco_eur "
        f"FROM {CAT}.{SCH}.inventory_transactions it "
        f"JOIN {CAT}.{SCH}.ingredients i ON it.ingredient_id = i.ingredient_id "
        f"JOIN {CAT}.{SCH}.stores s ON it.store_id = s.store_id "
        f"WHERE it.transaction_type = 'waste' "
        f"GROUP BY i.name, s.name ORDER BY costo_spreco_eur DESC LIMIT 20"
    ),
)

space.validate()

# The API requires id-bearing lists (example_question_sqls, benchmarks) sorted by id.
inner_dict = space.to_dict()


def _sort_by_id(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("example_question_sqls", "benchmarks", "example_sqls") and isinstance(v, list):
                v.sort(key=lambda e: e.get("id", "") if isinstance(e, dict) else "")
            _sort_by_id(v)
    elif isinstance(obj, list):
        for item in obj:
            _sort_by_id(item)


_sort_by_id(inner_dict)
serialized = json.dumps(inner_dict)  # JSON-encoded string of the inner serialized_space
create_payload = {
    "title": GENIE_SPACE_TITLE,
    "description": "Analisi vendite, scorte, clienti e promozioni della catena italiana di paninoteche Panino Bricks.",
    "parent_path": parent_path,
    "warehouse_id": WH,
    "serialized_space": serialized,
}
with open(args.out, "w") as f:
    json.dump(create_payload, f, indent=2)

inner = json.loads(serialized)
print("Genie space payload written to", args.out)
print("  tables:", len(inner.get("data_sources", {}).get("tables", [])))

# Create the space via REST.
resp, err = databricks_api("POST", "/api/2.0/genie/spaces", profile=args.profile, body=create_payload)
if resp is None:
    sys.exit(f"Create Genie space failed: {err}")
space_id = resp.get("space_id") or resp.get("id")
print(f"Created Genie space.")
print(f"\nGENIE_SPACE_ID={space_id}")
