# Panino Bricks Lab — Multi-Agent Demo on Databricks

![Panino Bricks](assets/logo.png)

A fully reproducible, self-contained lab that builds an end-to-end **multi-agent
AI application** on Databricks, using a fictional Italian panino (sandwich) chain
— **Panino Bricks** — as the use case. Run the provisioning orchestrator against
**any serverless Databricks workspace** in a supported region and you get
synthetic data, a Genie space, a Knowledge Assistant (RAG), a Multi-Agent
Supervisor, a Lakebase (Postgres) instance for chat memory, and a Streamlit app
that ties it all together.

> Demo **content** (data, PDFs, app UI) is in **Italian**. Repo **docs and code**
> are in **English** so the lab is shareable and professional.

> **Source / credits:** this lab is a reskin of the internal Databricks Field
> Engineering demo [`AstronomerAmber/AI_Days26`](https://github.com/AstronomerAmber/AI_Days26)
> ("BobaBricks"), adapted into an Italian panino chain ("Panino Bricks").

---

## What the lab builds

```
Streamlit App (Databricks App)
│  - Chat UI + Italian store selector
│  - Conversation history persisted in Lakebase (Postgres, OAuth token auto-refresh)
│
└── Multi-Agent Supervisor  (MAS serving endpoint, "Panino Bricks HQ")
    ├── Genie Space          — natural-language SQL over 13 Delta tables ("Analista Vendite")
    └── Knowledge Assistant  — RAG over 6 internal Italian PDFs ("Ops Bot")
```

The supervisor routes each question to the right subagent (structured data ->
Genie; recipes/procedures/HACCP/franchising -> Knowledge Assistant) and
synthesizes a single Italian answer. The app reads/writes chat history in
Lakebase. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full picture,
the data model, and the demo questions.

---

## Repository structure

```
panino-bricks-lab/
├── databricks.yml          # DAB bundle: variables + targets (dev); deploys the app
├── README.md               # this runbook
├── config.py               # single source of truth (brand, catalog, schema, endpoints) — all env-overridable
├── requirements.txt        # provisioning/orchestrator deps
├── provision_lab.py        # ORCHESTRATOR: runs steps 01..07, wires the MAS endpoint into the app
├── resources/
│   └── app.yml             # DAB app resource (Streamlit)
├── src/
│   ├── _common.py                      # shared auth + REST helpers (laptop or in-workspace)
│   ├── 01_generate_data.py             # 13 synthetic Delta tables
│   ├── 02_generate_ka_documents.py     # 6 Italian PDFs -> UC Volume
│   ├── 03_create_genie_space.py        # Genie space (genie-rooms builder + REST)
│   ├── 04_create_knowledge_assistant.py# Agent Bricks KA (REST /api/2.1/knowledge-assistants)
│   ├── 05_create_supervisor_agent.py   # Agent Bricks MAS (REST /api/2.1/supervisor-agents)
│   ├── 06_grant_app_permissions.py     # grant the app SP UC + endpoint + Genie + warehouse ACLs
│   └── 07_grant_lakebase_role.py       # Lakebase OAuth Postgres role for the app SP
├── app/                    # the Streamlit app (app.py + config.py + app.yaml + requirements.txt)
└── docs/
    └── ARCHITECTURE.md
```

Every script runs **standalone** (`python src/0X_*.py --profile <ws> ...`) and is
also driven by `provision_lab.py`.

---

## Prerequisites

1. **Workspace type / region.** A **serverless** Databricks workspace in a region
   where **Agent Bricks** (Genie + Knowledge Assistant + Supervisor) and
   **Lakebase** are available — e.g. AWS `eu-central-1` or `us-east-1`. A
   field-engineering FEVM workspace works well.
2. **Serverless budget policy > 0.** Agent Bricks and serverless compute require a
   serverless budget policy at the account level. Verify it before you start; a
   `$0` (or missing) policy makes endpoint creation fail.
3. **Catalog with Default Storage.** Create the target catalog **via the UI** with
   **Default Storage** enabled. A plain `CREATE CATALOG` on a fresh workspace fails
   with *"Metastore storage root URL does not exist"*. The scripts only
   `USE CATALOG` (verify it exists), then create the schema and volumes inside it.
4. **A running SQL warehouse** (serverless is fine). Scripts auto-discover one, or
   pass `--warehouse-id`.
5. **Databricks CLI** (recent: `databricks --version`, v0.230+ recommended) and
   **Python 3.10+**.
6. **The vibe `genie-rooms` skill** (provides `genie_space_builder`) for step 03.
   If its resources are not on the default cached path, set `GENIE_BUILDER_PATH`
   to its `resources/` directory.

---

## Runbook (4 steps)

### 1) Prerequisites
Confirm the 6 items above. In particular: catalog created via UI with Default
Storage, serverless budget policy > 0, region supports Agent Bricks + Lakebase.

### 2) Install + authenticate
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
databricks auth login --host https://<your-workspace-host>   # creates/uses a CLI profile
```
Note the **profile name** you create (used as `--profile <ws>` below).

### 3) Provision the lab (data + agents + Lakebase), then deploy the app

**Phase A** — everything except the app SP grants:
```bash
python provision_lab.py --profile <ws> --catalog <your_catalog>
```
This runs, in order: data generation, KA PDFs, Lakebase instance, Genie space,
Knowledge Assistant, Multi-Agent Supervisor. It captures the auto-named MAS
endpoint and **wires it into `app/app.yaml`**, then prints a summary with the
endpoint names and the next commands. It also writes `.lab_state.json` (ignored by
git) so Phase B can reuse the captured ids.

Then **deploy the app** with the DAB (this is what creates the app's service
principal):
```bash
databricks bundle deploy -t dev -p <ws> \
  --var="mas_endpoint_name=<mas-endpoint-from-summary>" \
  --var="catalog=<your_catalog>" --var="schema=panino_bricks"
```

**Phase B** — grant the freshly created app SP everything it needs. Find the app's
**service principal application id** on the app's resource page in the workspace
UI, then:
```bash
python provision_lab.py --profile <ws> --grants-only --sp <app-sp-application-id>
```
This grants UC (USE CATALOG / USE SCHEMA / SELECT), warehouse CAN_USE, CAN_QUERY
on the MAS and KA endpoints, CAN_RUN on the Genie space, and creates the Lakebase
OAuth role for the SP.

### 4) Open the app
Open the app URL printed by `databricks bundle deploy` (or from the workspace
**Compute > Apps** page). If you ran Phase B after the first deploy, redeploy or
restart the app so it picks up the new permissions.

---

## What each step creates & expected runtime

| Step | Creates | ~Runtime |
|---|---|---|
| 01 generate_data | 13 Delta tables (~200K orders, 15K customers, 37 stores, 29 panini) over a 3-month window | 3-6 min |
| 02 generate_ka_documents | 6 Italian PDFs in `…/ka_documents` Volume | < 1 min |
| Lakebase instance | `panino-bricks` Postgres instance (CU_1, pg-native-login) | 2-5 min to become available |
| 03 Genie space | "Panino Bricks - Vendite & Operations" over the 13 tables | < 1 min |
| 04 Knowledge Assistant | KA + knowledge source on the PDF Volume; async indexing | create < 1 min; indexing several min |
| 05 Supervisor (MAS) | Multi-Agent Supervisor + 2 tools; serving endpoint `mas-<hash>-endpoint` | create < 1 min; endpoint ACTIVE several min |
| 06 grant_app_permissions | UC + warehouse + endpoint + Genie ACLs for the app SP | < 1 min |
| 07 grant_lakebase_role | `databricks_auth` OAuth role for the app SP | < 1 min |
| `bundle deploy` | Databricks App + its service principal | 1-3 min |

Total wall-clock is dominated by data generation and waiting for the MAS/KA
endpoints to reach `ACTIVE` and indexing to finish.

---

## Configuration

`config.py` is the single source of truth. Every value is overridable via env var
(and the orchestrator/bundle set them for you):

| Setting | Env var | Default |
|---|---|---|
| Catalog | `PB_CATALOG` | `panino_bricks_catalog` |
| Schema | `PB_SCHEMA` | `panino_bricks` |
| Data Volume | `PB_VOLUME_NAME` | `raw_data` |
| KA Volume | `PB_KA_VOLUME_NAME` | `ka_documents` |
| Warehouse | `PB_WAREHOUSE_ID` | auto-discover |
| MAS endpoint | `MAS_ENDPOINT_NAME` | wired in by orchestrator |
| Lakebase instance | `LAKEBASE_INSTANCE_NAME` | `panino-bricks` |
| Lakebase database | `LAKEBASE_DATABASE_NAME` | `databricks_postgres` |
| Brand name | `PB_BRAND_NAME` | `Panino Bricks` |

A full rebrand to another chain = change `PB_BRAND_*` (and re-run the data step).

---

## Troubleshooting

**`CREATE CATALOG` fails: "Metastore storage root URL does not exist".**
The workspace's metastore has no storage root. Do **not** try to create the
catalog from SQL. Create it **via the UI with Default Storage** (prerequisite #3).
The scripts only `USE CATALOG` to verify it exists.

**Lakebase: `password authentication failed for user '<sp_application_id>'`.**
A plain `CREATE ROLE` makes a native-password role that does NOT work for OAuth.
The app SP needs a role created via the `databricks_auth` extension. That is
exactly what step 07 / `--grants-only` does:
```sql
CREATE EXTENSION IF NOT EXISTS databricks_auth;
SELECT databricks_create_role('<sp_application_id>', 'SERVICE_PRINCIPAL');
GRANT CREATE, CONNECT, TEMPORARY ON DATABASE databricks_postgres TO "<sp_id>";
```
Granting CAN_USE on the instance and attaching the Lakebase app-resource is
necessary but **not sufficient** on its own.

**Endpoint creation hangs or fails / "no serverless budget".**
You are in a region without Agent Bricks/Lakebase, or the account-level serverless
**budget policy is $0 or missing**. Move to a supported region (e.g.
`eu-central-1`, `us-east-1`) and ensure a serverless budget policy > 0.

**I don't know the MAS endpoint name.**
It is auto-named `mas-<hash>-endpoint` at creation. Phase A prints it (`MAS_ENDPOINT=...`),
saves it to `.lab_state.json`, and writes it into `app/app.yaml`. You can also list
serving endpoints: `databricks serving-endpoints list -p <ws>`.

**App shows "Disconnesso" / Lakebase panel red.**
The app SP can't reach Lakebase yet. Run Phase B (`--grants-only --sp <id>`) and
restart the app. Also confirm the Lakebase instance reached the *Available* state.

**OAuth token expired (CLI or Lakebase credential errors).**
Re-authenticate: `databricks auth login --host <host>`. The app refreshes its
Lakebase token automatically (~50-minute margin); the CLI profile is what expires
during long sessions.

**KA returns "I don't have that information".**
Indexing is asynchronous and may still be running, or the PDFs didn't land in the
Volume. Re-run step 02, then re-trigger sync (step 04 is idempotent and re-issues
`:syncKnowledgeSources`).

**Genie step can't import `genie_space_builder`.**
Install/enable the vibe `genie-rooms` skill, or set `GENIE_BUILDER_PATH` to its
`resources/` directory.

**SDK parse errors creating KA/MAS.**
Known: the Python SDK 0.114 fails to *parse* the create responses even though the
server creates the objects. The scripts already call REST via the CLI
(`databricks api … --json @file`) to avoid this. Don't switch them back to the SDK
create calls.

---

## Tear down

```bash
# 1) Remove the app (and its bundle-managed resources)
databricks bundle destroy -t dev -p <ws>

# 2) Delete the Agent Bricks objects (supervisor, KA) and the Genie space from the UI,
#    or via REST:
#    databricks api delete /api/2.1/supervisor-agents/<id> -p <ws>
#    databricks api delete /api/2.1/knowledge-assistants/<id> -p <ws>
#    databricks api delete /api/2.0/genie/spaces/<space_id> -p <ws>

# 3) Delete the Lakebase instance
databricks database delete-database-instance panino-bricks -p <ws>

# 4) Drop the schema (and volumes/tables). The catalog itself is left in place
#    (you created it via the UI).
#    DROP SCHEMA panino_bricks_catalog.panino_bricks CASCADE;
```
Ids are in `.lab_state.json` from the provisioning run.

---

## Notes

- Synthetic data only — no customer/PII data.
- The supervisor runs tools **as the caller** (the app SP), which is why the app SP
  needs CAN_QUERY/CAN_RUN/UC grants (step 06), not just the human's permissions.
- Reskin origin: the internal Field Engineering demo `AstronomerAmber/AI_Days26`
  (BobaBricks), localized to an Italian panino chain.
