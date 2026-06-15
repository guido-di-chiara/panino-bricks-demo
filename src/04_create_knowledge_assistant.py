"""Step 04 - Create (idempotently) the Panino Bricks Knowledge Assistant.

RAG over the 6 KA PDFs uploaded to the KA Volume by step 02.

Uses the Knowledge Assistants REST API (/api/2.1/knowledge-assistants) via the
Databricks CLI. We call REST directly because the Python SDK (0.114) fails to
*parse* the create responses even though the server succeeds.

Prints KA_ID and KA_ENDPOINT (the orchestrator reads them for step 05).

Run standalone:
  python src/04_create_knowledge_assistant.py --profile <ws> --catalog <cat>
"""
import os
import sys
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

parser = argparse.ArgumentParser(description="Create Panino Bricks Knowledge Assistant")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit in-workspace)")
parser.add_argument("--catalog", default=None, help="Override PB_CATALOG")
parser.add_argument("--schema", default=None, help="Override PB_SCHEMA")
args = parser.parse_args()

if args.catalog:
    os.environ["PB_CATALOG"] = args.catalog
if args.schema:
    os.environ["PB_SCHEMA"] = args.schema

from config import KA_DISPLAY_NAME, KA_VOLUME_PATH  # noqa: E402
from _common import databricks_api  # noqa: E402

P = args.profile
KA_NAME = KA_DISPLAY_NAME
SOURCE_NAME = "Documenti Interni Panino Bricks"
INSTRUCTIONS = (
    "Sei l'assistente operativo di Panino Bricks, catena italiana di paninoteche. "
    "Rispondi SEMPRE in italiano, basandoti esclusivamente sui documenti interni forniti "
    "(manuale operatore, ricettario panini, politica di sicurezza alimentare HACCP e allergeni, "
    "guida franchising, manutenzione attrezzature, accordi fornitori). "
    "Per domande su allergeni o idoneita' a diete particolari (es. clienti celiaci), cita sempre "
    "la politica di sicurezza alimentare e ricorda che i panini contengono glutine e che non c'e' "
    "garanzia gluten-free per contaminazione crociata. "
    "Se l'informazione non e' presente nei documenti, dillo chiaramente invece di inventare."
)


def api(method, path, body=None):
    return databricks_api(method, path, profile=P, body=body)


# 1. Find or create the assistant (idempotent on display_name)
listing, _ = api("GET", "/api/2.1/knowledge-assistants")
ka = None
for k in (listing or {}).get("knowledge_assistants", []):
    if k.get("display_name") == KA_NAME:
        ka = k
        break
if ka is None:
    ka, err = api("POST", "/api/2.1/knowledge-assistants", {
        "display_name": KA_NAME,
        "description": "RAG sui documenti interni di Panino Bricks.",
        "instructions": INSTRUCTIONS,
    })
    if ka is None:
        sys.exit(f"Create KA failed: {err}")
    print(f"Created KA: {ka['id']}")
else:
    print(f"Reusing KA: {ka['id']}")

ka_path = ka["name"]  # knowledge-assistants/<id>
print(f"  endpoint_name={ka.get('endpoint_name')}")

# 2. Find or create the knowledge source on the PDF Volume
srcs, _ = api("GET", f"/api/2.1/{ka_path}/knowledge-sources")
have_src = any(s.get("display_name") == SOURCE_NAME for s in (srcs or {}).get("knowledge_sources", []))
if not have_src:
    src, err = api("POST", f"/api/2.1/{ka_path}/knowledge-sources", {
        "display_name": SOURCE_NAME,
        "description": "6 PDF: manuale operatore, ricettario, HACCP/allergeni, franchising, manutenzione, fornitori.",
        "source_type": "files",
        "files": {"path": KA_VOLUME_PATH},
    })
    if src is None:
        sys.exit(f"Create source failed: {err}")
    print(f"Created knowledge source: {src['id']}")
else:
    print("Knowledge source already present.")

# 3. Trigger indexing (asynchronous)
api("POST", f"/api/2.1/{ka_path}:syncKnowledgeSources")
print("Sync requested - indexing runs asynchronously.")

print(f"\nKA_ID={ka['id']}")
print(f"KA_ENDPOINT={ka.get('endpoint_name')}")
