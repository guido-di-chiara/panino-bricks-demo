import os
import re
import json
import uuid
import time
import threading

import psycopg2
import psycopg2.extras
import requests
import streamlit as st
from databricks.sdk import WorkspaceClient

from config import (  # noqa: E402
    MAS_ENDPOINT_NAME,
    LAKEBASE_INSTANCE_NAME,
    LAKEBASE_DATABASE_NAME,
    BRAND_NAME,
    BRAND_TAGLINE,
    BRAND_DESCRIPTION,
    BRAND_PAGE_ICON,
    STORE_PREFIX,
    KA_VOLUME_PATH,
)

st.set_page_config(
    page_title=f"{BRAND_NAME} {BRAND_TAGLINE}",
    page_icon=BRAND_PAGE_ICON,
    layout="centered",
)

_logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.png")
if os.path.exists(_logo_path):
    st.image(_logo_path, width=320)
else:
    st.title(BRAND_NAME)
st.caption(BRAND_TAGLINE)
st.markdown(BRAND_DESCRIPTION)


# --- Lakebase connection ---
# The app's service principal has CAN_CONNECT_AND_CREATE on the panino-bricks
# Lakebase instance. WorkspaceClient() inside Databricks Apps auto-uses the SP.

_token_lock = threading.Lock()
_cached_token = None
_token_expiry = 0
TOKEN_REFRESH_MARGIN = 50 * 60


def _generate_lakebase_token() -> str:
    w = WorkspaceClient()
    cred = w.database.generate_database_credential(
        request_id=str(uuid.uuid4()),
        instance_names=[LAKEBASE_INSTANCE_NAME],
    )
    return cred.token


def get_lakebase_token() -> str:
    global _cached_token, _token_expiry
    with _token_lock:
        if _cached_token is None or time.time() >= _token_expiry:
            _cached_token = _generate_lakebase_token()
            _token_expiry = time.time() + TOKEN_REFRESH_MARGIN
        return _cached_token


def get_db_connection():
    w = WorkspaceClient()
    instance = w.database.get_database_instance(name=LAKEBASE_INSTANCE_NAME)
    token = get_lakebase_token()
    me = w.current_user.me()
    conn = psycopg2.connect(
        host=instance.read_write_dns,
        database=LAKEBASE_DATABASE_NAME,
        user=me.user_name,
        password=token,
        port=5432,
        sslmode="require",
        connect_timeout=10,
    )
    conn.autocommit = True
    return conn


@st.cache_resource
def get_cached_connection():
    return get_db_connection()


def get_conn():
    try:
        conn = get_cached_connection()
        conn.cursor().execute("SELECT 1")
        return conn
    except Exception:
        get_cached_connection.clear()
        return get_cached_connection()


def init_db():
    """Create schema and tables if they don't exist."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS panino_app")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS panino_app.conversations (
                id TEXT PRIMARY KEY,
                title TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS panino_app.messages (
                id TEXT PRIMARY KEY,
                conversation_id TEXT REFERENCES panino_app.conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON panino_app.messages(conversation_id, created_at)
        """)


def get_db_stats():
    """Get database statistics."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM panino_app.conversations")
        conv_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM panino_app.messages")
        msg_count = cur.fetchone()[0]
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))")
        db_size = cur.fetchone()[0]
        cur.execute("SELECT version()")
        pg_version = cur.fetchone()[0].split(",")[0]
    return {
        "conversations": conv_count,
        "messages": msg_count,
        "db_size": db_size,
        "pg_version": pg_version,
    }


def load_conversations():
    """Load all conversations ordered by most recent."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, title, created_at FROM panino_app.conversations ORDER BY created_at DESC"
        )
        return cur.fetchall()


def load_messages(conversation_id: str):
    """Load messages for a conversation."""
    conn = get_conn()
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT role, content FROM panino_app.messages WHERE conversation_id = %s ORDER BY created_at",
            (conversation_id,),
        )
        return [dict(row) for row in cur.fetchall()]


def save_message(conversation_id: str, role: str, content: str):
    """Save a message to the database."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO panino_app.messages (id, conversation_id, role, content) VALUES (%s, %s, %s, %s)",
            (str(uuid.uuid4()), conversation_id, role, content),
        )


def create_conversation(title: str) -> str:
    """Create a new conversation and return its ID."""
    conv_id = str(uuid.uuid4())
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO panino_app.conversations (id, title) VALUES (%s, %s)",
            (conv_id, title),
        )
    return conv_id


def delete_all_conversations():
    """Delete all conversations and their messages from the database."""
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM panino_app.messages")
        cur.execute("DELETE FROM panino_app.conversations")


# --- MAS endpoint ---

@st.cache_resource
def get_workspace_client():
    return WorkspaceClient()


AGENT_DISPLAY_NAMES = {
    "Ops_bot": "Ops Bot",
    "PaninoBricks-HQ": f"{BRAND_NAME} HQ",
    "agent-panino-genie": "Analista Vendite",
}

# Known KA source documents: display name -> PDF filename
KA_DOC_FILES = {
    "Manuale Operatore": "manuale_operatore.pdf",
    "Ricettario Panini": "ricettario_panini.pdf",
    "Sicurezza Alimentare (HACCP)": "sicurezza_alimentare_haccp.pdf",
    "Guida Franchising": "guida_franchising.pdf",
    "Manutenzione Attrezzature": "manutenzione_attrezzature.pdf",
    "Accordi Fornitori": "accordi_fornitori.pdf",
}


def _extract_citations(full_text: str) -> list[str]:
    """Extract source document citations from response text."""
    citations = []
    seen = set()
    lower = full_text.lower()

    # Match .pdf filenames anywhere in the text (including Footnotes section)
    for pdf in re.findall(r'([\w_\-]+\.pdf)', full_text):
        name = pdf.replace("_", " ").replace(".pdf", "").title()
        if name not in seen:
            seen.add(name)
            citations.append(name)

    # Infer source documents from response content
    content_signals = {
        "Ricettario Panini": [r"PRD-\d{3}", r"ricett", r"panino", r"preparazione", r"farcit"],
        "Manuale Operatore": [r"operatore", r"formazione", r"servizio client", r"apertura", r"banco"],
        "Sicurezza Alimentare (HACCP)": [r"sicurezza aliment", r"allergen", r"haccp", r"catena del freddo", r"igien", r"sanific"],
        "Guida Franchising": [r"franchising", r"affiliaz", r"apertura.*punto vendita", r"grande apertura", r"royalt"],
        "Manutenzione Attrezzature": [r"manutenzione", r"attrezzatur", r"piastra", r"affettatrice", r"forno", r"frigo"],
        "Accordi Fornitori": [r"fornitor", r"lead.?time", r"SUP-\d{3}", r"riordin", r"consegna"],
    }
    for doc_name, patterns in content_signals.items():
        if doc_name not in seen:
            for pattern in patterns:
                if re.search(pattern, lower):
                    seen.add(doc_name)
                    citations.append(doc_name)
                    break

    return citations


def clean_response(full_text: str, extra_citations: list[str] | None = None) -> str:
    """Clean MAS response: strip footnotes, format agent names, add citations."""
    # Extract citations BEFORE stripping footnotes (filenames are in that section)
    citations = _extract_citations(full_text)
    if extra_citations:
        for c in extra_citations:
            if c not in citations:
                citations.append(c)

    text = full_text

    # Replace <name>...</name> tags with friendly labels
    def _clean_agent_name(m):
        raw = m.group(1)
        name = AGENT_DISPLAY_NAMES.get(raw, raw.replace("_", " ").replace("-", " "))
        return f"*Calling agent... {name}*"
    text = re.sub(r'<name>([^<]+)</name>', _clean_agent_name, text)

    # Remove any remaining XML/HTML tags
    text = re.sub(r'<[^>]+>', '', text)

    # Clean up excessive blank lines
    text = re.sub(r'\n{3,}', '\n\n', text).strip()

    # Append clean source citations with links to PDFs
    if citations:
        host = get_workspace_client().config.host.rstrip("/")
        parts = []
        for c in citations:
            fname = KA_DOC_FILES.get(c)
            if fname:
                url = f"{host}/api/2.0/fs/files{KA_VOLUME_PATH}/{fname}"
                parts.append(f"[{c}]({url})")
            else:
                parts.append(f"*{c}*")
        text += f"\n\n---\n**Sources:** {', '.join(parts)}"

    return text if text else "No response from agent."


def stream_mas(messages: list[dict]):
    """Generator that yields text deltas from the MAS streaming endpoint."""
    w = get_workspace_client()
    url = f"{w.config.host.rstrip('/')}/serving-endpoints/{MAS_ENDPOINT_NAME}/invocations"
    headers = w.config.authenticate()
    headers["Content-Type"] = "application/json"

    resp = requests.post(
        url, headers=headers,
        json={"input": messages, "stream": True},
        stream=True, timeout=300,
    )
    resp.raise_for_status()

    emitted_agents = set()

    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
            event_type = event.get("type", "")

            # Detect agent name from output_item events
            if event_type in ("response.output_item.added", "response.output_item.done"):
                item = event.get("item", {})
                agent_raw = None
                # Agent name as <name>X</name> inside content text
                for block in item.get("content", []):
                    txt = block.get("text", "")
                    m = re.match(r'^<name>([^<]+)</name>$', txt.strip())
                    if m:
                        agent_raw = m.group(1)
                # Function call to a sub-agent
                if not agent_raw and item.get("type") == "function_call" and item.get("name"):
                    agent_raw = item["name"]
                # Emit once per agent
                if agent_raw and agent_raw not in emitted_agents:
                    emitted_agents.add(agent_raw)
                    display = AGENT_DISPLAY_NAMES.get(agent_raw, agent_raw.replace("_", " ").replace("-", " "))
                    yield f"\n\n*Calling agent... {display}*\n\n"

            # Handle Responses API text deltas
            if event_type == "response.output_text.delta":
                yield event.get("delta", "")

            # Handle generic delta format
            elif "delta" in event:
                d = event["delta"]
                yield d if isinstance(d, str) else d.get("content", "")
        except json.JSONDecodeError:
            continue


def query_mas(messages: list[dict]) -> str:
    """Non-streaming fallback: send messages and return cleaned response."""
    w = get_workspace_client()
    url = f"{w.config.host.rstrip('/')}/serving-endpoints/{MAS_ENDPOINT_NAME}/invocations"
    headers = w.config.authenticate()
    headers["Content-Type"] = "application/json"

    resp = requests.post(url, headers=headers, json={"input": messages}, timeout=300)
    resp.raise_for_status()
    data = resp.json()

    parts = []
    for item in data.get("output", []):
        if item.get("type") == "message":
            for block in item.get("content", []):
                if block.get("type") == "output_text":
                    parts.append(block["text"])
    full_text = "\n\n".join(parts) if parts else "No response from agent."
    return clean_response(full_text)


# --- Initialize ---

def _init_with_timeout(timeout=15):
    result = {"ok": False, "error": None}
    def _run():
        try:
            # init_db()
            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result

if "db_available" not in st.session_state:
    r = _init_with_timeout()
    st.session_state.db_available = r["ok"]
    st.session_state["db_error"] = r["error"]

if "conversation_id" not in st.session_state:
    st.session_state.conversation_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- CSS for blinking indicator ---

st.markdown("""
<style>
@keyframes blink {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.2; }
}
.db-active {
    animation: blink 1s ease-in-out infinite;
}
.db-dot {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
}
.db-dot-green { background-color: #22c55e; }
.db-dot-gray { background-color: #9ca3af; }
.lakebase-panel {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid #2d3a4a;
    border-radius: 8px;
    padding: 14px;
    margin-bottom: 12px;
    color: #e2e8f0;
    font-size: 13px;
}
.lakebase-panel .label {
    color: #94a3b8;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-bottom: 2px;
}
.lakebase-panel .value {
    color: #f1f5f9;
    font-weight: 500;
    font-family: monospace;
    font-size: 12px;
}
.stat-row {
    display: flex;
    justify-content: space-between;
    padding: 4px 0;
}
</style>
""", unsafe_allow_html=True)

# --- Sidebar ---

with st.sidebar:
    # Lakebase status panel
    stats = None
    db_connected = False
    if st.session_state.db_available:
        try:
            stats = get_db_stats()
            db_connected = True
        except Exception:
            pass

    dot_class = "db-dot-green db-active" if db_connected else "db-dot-gray"
    status_text = "Connesso" if db_connected else "Disconnesso"

    st.markdown(f"""
    <div class="lakebase-panel">
        <div style="display: flex; align-items: center; margin-bottom: 10px;">
            <span class="db-dot {dot_class}"></span>
            <strong style="font-size: 14px;">LAKEBASE</strong>
            <span style="margin-left: auto; font-size: 11px; color: #22c55e;">{status_text}</span>
        </div>
        <div class="label">Instance</div>
        <div class="value">{LAKEBASE_INSTANCE_NAME}</div>
        <div class="label" style="margin-top: 8px;">Database</div>
        <div class="value">{LAKEBASE_DATABASE_NAME}</div>
    </div>
    """, unsafe_allow_html=True)

    if not db_connected and st.session_state.get("db_error"):
        st.caption(f"⚠️ {st.session_state.db_error}")

    if stats:
        col1, col2, col3 = st.columns(3)
        col1.metric("Chat", stats["conversations"])
        col2.metric("Messaggi", stats["messages"])
        col3.metric("Dimensione", stats["db_size"])

        with st.expander("Dettagli Memoria (Lakebase)"):
            st.caption(f"**Motore:** {stats['pg_version']}")
            st.caption(f"**Istanza:** {LAKEBASE_INSTANCE_NAME}")
            st.caption(f"**Database:** {LAKEBASE_DATABASE_NAME}")
            st.caption(f"**Auth:** token OAuth (auto-refresh)")
            st.caption(f"**Tabelle:** conversations, messages")
            st.caption(f"**Totale salvato:** {stats['conversations']} chat, {stats['messages']} messaggi")

    st.divider()

    # Store selector
    st.markdown("**Punto Vendita**")

    STORES = {
        "Ancona Centro": "STR-040 — Ancona Centro",
        "Bari Murat": "STR-017 — Bari Murat",
        "Bergamo Bassa": "STR-019 — Bergamo Bassa",
        "Bologna Centro": "STR-009 — Bologna Centro",
        "Bolzano Centro": "STR-041 — Bolzano Centro",
        "Brescia Centro": "STR-021 — Brescia Centro",
        "Cagliari Marina": "STR-032 — Cagliari Marina",
        "Catania Centro": "STR-029 — Catania Centro",
        "Como Lago": "STR-035 — Como Lago",
        "Firenze Oltrarno": "STR-011 — Firenze Oltrarno",
        "Genova Centro": "STR-016 — Genova Centro",
        "Lecce Centro": "STR-038 — Lecce Centro",
        "Milano Brera": "STR-006 — Milano Brera",
        "Milano Isola": "STR-018 — Milano Isola",
        "Milano Navigli": "STR-005 — Milano Navigli",
        "Modena Centro": "STR-023 — Modena Centro",
        "Monza Centro": "STR-036 — Monza Centro",
        "Napoli Chiaia": "STR-012 — Napoli Chiaia",
        "Padova Centro": "STR-015 — Padova Centro",
        "Palermo Centro": "STR-028 — Palermo Centro",
        "Parma Centro": "STR-022 — Parma Centro",
        "Perugia Centro": "STR-031 — Perugia Centro",
        "Pescara Centro": "STR-042 — Pescara Centro",
        "Pisa Centro": "STR-033 — Pisa Centro",
        "Rimini Marina": "STR-030 — Rimini Marina",
        "Roma EUR": "STR-020 — Roma EUR",
        "Roma Monti": "STR-013 — Roma Monti",
        "Roma Prati": "STR-034 — Roma Prati",
        "Roma Trastevere": "STR-007 — Roma Trastevere",
        "Salerno Lungomare": "STR-039 — Salerno Lungomare",
        "Torino Quadrilatero": "STR-027 — Torino Quadrilatero",
        "Torino San Salvario": "STR-010 — Torino San Salvario",
        "Trento Centro": "STR-026 — Trento Centro",
        "Trieste Centro": "STR-024 — Trieste Centro",
        "Venezia Mestre": "STR-025 — Venezia Mestre",
        "Verona Centro": "STR-014 — Verona Centro",
        "Vicenza Centro": "STR-037 — Vicenza Centro",
    }

    if "store_location" not in st.session_state:
        st.session_state.store_location = "Milano Navigli"

    selected = st.selectbox(
        "Punto Vendita",
        list(STORES.keys()),
        index=list(STORES.keys()).index(st.session_state.store_location),
        key="store_select",
    )
    st.session_state.store_location = selected
    st.caption(f"📍 {STORES[selected]}")

    st.divider()

    # About section
    st.markdown(f"""
**Info**

Questo assistente è guidato dal **Supervisor {BRAND_NAME} HQ**, che instrada la tua richiesta agli specialisti:

🥪 **Ops Bot** *(Knowledge Assistant)* — Ricette, formazione, sicurezza alimentare e info fornitori via RAG sui documenti interni

📊 **Analista Vendite** *(Genie Space)* — Vendite, scorte e dati clienti in tempo reale via SQL in linguaggio naturale

`Endpoint: {MAS_ENDPOINT_NAME}`

*Realizzato con Databricks Apps & Databricks AI*
""")

    st.divider()
    st.header("Conversazioni")

    # col_new, col_clear = st.columns(2)
    # with col_new:
    #     if st.button("Nuova Chat", use_container_width=True):
    #         st.session_state.conversation_id = None
    #         st.session_state.messages = []
    #         st.session_state.viewing_history = False
    #         st.rerun()
    # with col_clear:
    #     if st.button("Cancella Cronologia", use_container_width=True):
    #         if st.session_state.db_available:
    #             try:
    #                 delete_all_conversations()
    #             except Exception:
    #                 pass
    #         st.session_state.conversation_id = None
    #         st.session_state.messages = []
    #         st.rerun()
    if st.button("Nuova Chat", use_container_width=True):
        st.session_state.conversation_id = None
        st.session_state.messages = []
        st.session_state.viewing_history = False
        st.rerun()

    st.divider()

    conversations = load_conversations() if st.session_state.db_available else []
    for conv in conversations:
        label = conv["title"] or "Senza titolo"
        if st.button(
            label,
            key=conv["id"],
            use_container_width=True,
            type="secondary" if conv["id"] != st.session_state.conversation_id else "primary",
        ):
            st.session_state.conversation_id = conv["id"]
            st.session_state.messages = load_messages(conv["id"])
            st.session_state.viewing_history = True
            st.rerun()

# --- Main chat ---

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])


examples = [
    "Qual è il panino più venduto questo mese?",
    "Come si prepara il panino 'Nduja & Friarielli?",
    "Quali punti vendita stanno per finire la mozzarella?",
    "Quali promozioni sono attive adesso?",
    "Quanto tempo serve per riordinare il tartufo dal fornitore?",
]

last_role = st.session_state.messages[-1]["role"] if st.session_state.messages else None
if last_role in (None, "assistant"):
    st.markdown("**Prova a chiedere:**")
    for ex in examples:
        if st.button(f'"{ex}"', key=f"ex_{ex}", use_container_width=True):
            st.session_state.example_prompt = ex
            st.rerun()

# Handle clicked example prompt
prompt = None
if "example_prompt" in st.session_state:
    prompt = st.session_state.pop("example_prompt")

typed = st.chat_input("Chiedi di panini, ricette, vendite, scorte o operatività...")
if typed:
    prompt = typed

if prompt:
    if st.session_state.conversation_id is None:
        title = prompt[:50] + ("..." if len(prompt) > 50 else "")
        conv_id = str(uuid.uuid4())
        if st.session_state.db_available:
            try:
                conv_id = create_conversation(title)
            except Exception:
                pass
        st.session_state.conversation_id = conv_id

    st.session_state.viewing_history = False
    st.session_state.messages.append({"role": "user", "content": prompt})
    if st.session_state.db_available:
        try:
            save_message(st.session_state.conversation_id, "user", prompt)
        except Exception:
            pass
    with st.chat_message("user"):
        st.markdown(prompt)

    location_ctx = f"[Sede: {STORE_PREFIX} {st.session_state.store_location}] "
    input_messages = [
        {"role": m["role"], "content": (location_ctx + m["content"] if i == 0 and m["role"] == "user" else m["content"])}
        for i, m in enumerate(st.session_state.messages)
    ]

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown(f"*Interpello l'agente... {BRAND_NAME} HQ*")
        raw_text = f"*Interpello l'agente... {BRAND_NAME} HQ*\n\n"
        try:
            for chunk in stream_mas(input_messages):
                raw_text += chunk
                # Light clean for live display
                display = re.sub(r'<name>([^<]+)</name>',
                    lambda m: f"*Calling agent... {AGENT_DISPLAY_NAMES.get(m.group(1), m.group(1))}*",
                    raw_text)
                placeholder.markdown(display)
            response = clean_response(raw_text)
        except Exception:
            with st.spinner("Sto pensando..."):
                response = query_mas(input_messages)
        placeholder.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
    if st.session_state.db_available:
        try:
            save_message(st.session_state.conversation_id, "assistant", response)
        except Exception:
            pass
