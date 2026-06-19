"""Step 05 - Create (idempotently) the Panino Bricks Multi-Agent Supervisor (MAS).

Coordinates two subagents:
  - Genie space          (Analista Vendite) -> structured sales/ops data
  - Knowledge Assistant  (Ops Bot)          -> RAG over the internal PDFs

Uses the REST API (/api/2.1/supervisor-agents) via the Databricks CLI - the
Python SDK 0.114 fails to *parse* the create responses (server creates fine).

The MAS serving endpoint is AUTO-NAMED `mas-<hash>-endpoint`; this script prints
MAS_ENDPOINT so the orchestrator can wire it into the app.

Run standalone:
  python src/05_create_supervisor_agent.py --profile <ws> \
      --genie-space-id <id> --ka-id <id> --ka-endpoint <name>
"""
import os
import sys
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # repo root (config.py)
sys.path.insert(0, _HERE)                    # src/ (_common.py)

parser = argparse.ArgumentParser(description="Create Panino Bricks Supervisor Agent")
parser.add_argument("--profile", default=None, help="Databricks CLI profile (omit in-workspace)")
parser.add_argument("--genie-space-id", required=True, help="Genie space id from step 03")
parser.add_argument("--ka-id", required=True, help="Knowledge Assistant id from step 04")
parser.add_argument("--ka-endpoint", required=True, help="KA serving endpoint name from step 04")
args = parser.parse_args()

from config import SUPERVISOR_DISPLAY_NAME  # noqa: E402
from _common import databricks_api  # noqa: E402

P = args.profile
SUP_NAME = SUPERVISOR_DISPLAY_NAME
INSTRUCTIONS = (
    "Sei il supervisore di Panino Bricks HQ, catena italiana di paninoteche. "
    "Rispondi SEMPRE in italiano. Instrada ogni richiesta al sottoagente giusto: "
    "usa 'Analista Vendite' (Genie) per domande su dati strutturati (vendite, scontrini, panini piu' venduti, "
    "scorte/magazzino, clienti, fedelta', promozioni, fatturato, performance per punto vendita); "
    "usa 'Ops Bot' (Knowledge Assistant) per ricette dei panini, procedure operative, sicurezza alimentare e "
    "allergeni (HACCP), franchising, manutenzione attrezzature e accordi con i fornitori. "
    "Per domande composte (che richiedono sia dati sia procedure) interpella entrambi i sottoagenti e sintetizza una risposta unica."
)


def api(method, path, body=None, query=None):
    return databricks_api(method, path, profile=P, body=body, query=query)


# 1. Find or create the supervisor
listing, _ = api("GET", "/api/2.1/supervisor-agents")
sup = None
for s in (listing or {}).get("supervisor_agents", []):
    if s.get("display_name") == SUP_NAME:
        sup = s
        break
if sup is None:
    sup, err = api("POST", "/api/2.1/supervisor-agents", {
        "display_name": SUP_NAME,
        "description": "Supervisore multi-agente Panino Bricks: instrada tra Genie (vendite/ops) e Knowledge Assistant (documenti).",
        "instructions": INSTRUCTIONS,
    })
    if sup is None:
        sys.exit(f"Create supervisor failed: {err}")
    print(f"Created supervisor: {sup.get('id') or sup.get('supervisor_agent_id', sup.get('name', ''))}")
else:
    print(f"Reusing supervisor: {sup.get('id') or sup.get('supervisor_agent_id', sup.get('name', ''))}")

sup_path = sup["name"]  # supervisor-agents/<id>
print(f"  endpoint_name={sup.get('endpoint_name')}")

# 2. Register tools (idempotent on tool_id)
existing, _ = api("GET", f"/api/2.1/{sup_path}/tools")
have = {t.get("tool_id") or t.get("id") for t in (existing or {}).get("tools", [])}

tools = [
    ("analista-vendite", {
        "tool_type": "genie_space",
        "description": "Analista Vendite: risponde a domande su dati strutturati di vendita, scontrini, panini, "
                       "scorte/magazzino, clienti, fedelta', promozioni e fatturato tramite SQL sui dati.",
        "genie_space": {"id": args.genie_space_id},
    }),
    ("ops-bot", {
        "tool_type": "knowledge_assistant",
        "description": "Ops Bot: risponde su ricette dei panini, procedure operative, sicurezza alimentare e "
                       "allergeni (HACCP), franchising, manutenzione e fornitori, dai documenti interni.",
        "knowledge_assistant": {
            "knowledge_assistant_id": args.ka_id,
            "serving_endpoint_name": args.ka_endpoint,
        },
    }),
]
for tool_id, body in tools:
    if tool_id in have:
        print(f"  tool '{tool_id}' already present")
        continue
    res, err = api("POST", f"/api/2.1/{sup_path}/tools", body, query={"tool_id": tool_id})
    print(f"  added tool '{tool_id}'" if res is not None or not err else f"  tool '{tool_id}' err: {err}")

print(f"\nMAS_ENDPOINT={sup.get('endpoint_name')}")
print(f"SUP_PATH={sup_path}")
