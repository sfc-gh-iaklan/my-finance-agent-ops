"""
utils.py
Shared utilities for the evaluation framework.
"""
import os
import json
import functools
import yaml
import requests
import snowflake.connector
from datetime import datetime


# ---------------------------------------------------------------------------
# Instance resolution + config loading
#
# The framework is domain-agnostic. Each deployment ("instance") is a directory
# that owns its environments/thresholds/monitoring/schedules config + its SV,
# agent, and question banks. The active instance is chosen by the AIOPS_INSTANCE
# env var and defaults to the repo's instance/ directory, so the framework works
# out-of-box and CI needs no extra vars.
# ---------------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_INSTANCE = os.path.join(REPO_ROOT, "instance")


def instance_dir() -> str:
    """Absolute path to the active instance/example directory."""
    return os.path.abspath(os.environ.get("AIOPS_INSTANCE", DEFAULT_INSTANCE))


def instance_path(*relative_parts: str) -> str:
    """Resolve a path that the instance config expresses relative to its own dir."""
    return os.path.join(instance_dir(), *relative_parts)


def framework_config_dir() -> str:
    """Directory holding framework-level defaults (config/defaults.yaml)."""
    return os.path.join(REPO_ROOT, "config")


def _read_yaml(path: str) -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` onto `base`. Override wins; nested dicts merge."""
    out = dict(base)
    for key, val in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(val, dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = val
    return out


def _pem_to_der(pem_data: bytes, passphrase: str = None) -> bytes:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    pw = passphrase.encode() if passphrase else None
    p_key = serialization.load_pem_private_key(pem_data, password=pw, backend=default_backend())
    return p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _load_private_key(key_path: str, passphrase: str = None) -> bytes:
    with open(os.path.expanduser(key_path), "rb") as f:
        return _pem_to_der(f.read(), passphrase)


def _private_key_from_env() -> bytes:
    """Load a PKCS8 private key from the SNOWFLAKE_PRIVATE_KEY env var.

    Accepts raw PEM (multi-line, or single-line with literal \\n escapes) or
    base64-encoded PEM. Optional passphrase via SNOWFLAKE_PRIVATE_KEY_PASSPHRASE.
    Returns None if the env var is unset. All inputs come from the environment
    so the framework stays generic across instances and CI providers.
    """
    raw = os.getenv("SNOWFLAKE_PRIVATE_KEY")
    if not raw:
        return None
    import base64
    if "-----BEGIN" in raw:
        data = raw.replace("\\n", "\n").encode()
    else:
        data = base64.b64decode(raw)
    return _pem_to_der(data, os.getenv("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"))


def _resolve_connection_params(connection_name: str) -> dict:
    try:
        import tomli
    except ImportError:
        import tomllib as tomli
    toml_path = os.path.expanduser("~/.snowflake/connections.toml")
    if not os.path.exists(toml_path):
        return {}
    with open(toml_path, "rb") as f:
        config = tomli.load(f)
    return config.get(connection_name, {})


def get_connection(environment: str = "dev") -> snowflake.connector.SnowflakeConnection:
    config = load_config()
    env_config = config["environments"][environment]

    # Resolve warehouse: new format uses framework.warehouse, old format uses env warehouse
    if _is_new_config_format(config):
        warehouse = config.get("framework", {}).get("warehouse", "COMPUTE_WH")
    else:
        warehouse = env_config.get("warehouse", "COMPUTE_WH")

    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    if account and user and os.getenv("SNOWFLAKE_PRIVATE_KEY"):
        # Headless / CI: key-pair (JWT) auth from environment. Preferred for
        # automation since SSO cannot run headless. All values from env vars.
        conn = snowflake.connector.connect(
            account=account,
            user=user,
            private_key=_private_key_from_env(),
            authenticator="snowflake_jwt",
            role=os.getenv("SNOWFLAKE_ROLE"),
            warehouse=warehouse,
        )
    elif account and user:
        # Env-var password auth (fallback when no key-pair is provided).
        conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=os.getenv("SNOWFLAKE_PASSWORD"),
            role=os.getenv("SNOWFLAKE_ROLE"),
            warehouse=warehouse,
        )
    else:
        conn_name = (os.getenv("SNOWFLAKE_CONNECTION_NAME")
                     or config.get("connection_name")
                     or env_config.get("connection_name", "default"))
        params = _resolve_connection_params(conn_name)
        key_path = params.get("private_key_path") or params.get("private_key_file")
        if key_path and params.get("authenticator") in ("snowflake_jwt", "SNOWFLAKE_JWT"):
            conn = snowflake.connector.connect(
                account=params["account"],
                user=params["user"],
                private_key=_load_private_key(key_path),
                role=params.get("role"),
                warehouse=warehouse,
            )
        else:
            conn = snowflake.connector.connect(connection_name=conn_name)
            conn.cursor().execute(f"USE WAREHOUSE {warehouse}")

    # Set context: for new format use framework DB; for old format use env DB
    if _is_new_config_format(config):
        fw = config.get("framework", {})
        conn.cursor().execute(f"USE DATABASE {fw['database']}")
        conn.cursor().execute(f"USE SCHEMA {fw['schema']}")
    else:
        conn.cursor().execute(f"USE DATABASE {env_config['database']}")
        conn.cursor().execute(f"USE SCHEMA {env_config.get('semantic_schema', env_config['schema'])}")
    return conn


@functools.lru_cache(maxsize=None)
def _load_config_cached(inst: str) -> dict:
    # Framework defaults (llm, pricing) merged UNDER the instance config.
    defaults = _read_yaml(os.path.join(framework_config_dir(), "defaults.yaml"))
    instance = _read_yaml(os.path.join(inst, "config", "environments.yaml"))
    return _deep_merge(defaults, instance)


def load_config() -> dict:
    """Merged config: framework defaults overlaid by the active instance config."""
    return _load_config_cached(instance_dir())


def _is_new_config_format(config: dict) -> bool:
    """Detect whether the config uses the new multi-object format.

    New format: environments.dev.semantic_views is a list.
    Old format: environments.dev.semantic_view is a string.
    """
    dev = config.get("environments", {}).get("dev", {})
    return isinstance(dev.get("semantic_views"), list)


def get_framework_config() -> dict:
    """Return the framework section (database, schema, warehouse for framework objects).

    Supports both config formats:
    - New format: config["framework"] with database/schema/warehouse
    - Old format: config["eval"] with database/schema mapped to framework equivalents
    """
    config = load_config()
    if "framework" in config:
        return config["framework"]
    # Backwards compat: map old 'eval' section to framework shape
    ev = config.get("eval", {})
    return {
        "database": ev.get("database", ""),
        "schema": ev.get("schema", "RESULTS"),
        "warehouse": ev.get("warehouse", ""),
    }


def get_semantic_views(environment: str = "dev") -> list:
    """Return list of semantic view dicts for an environment.

    New format returns the list directly. Old format wraps the single entry.
    Each dict has: {"fqn": "...", "short_name": "..."}
    """
    config = load_config()
    env = config["environments"][environment]
    if _is_new_config_format(config):
        return env.get("semantic_views", [])
    # Old format: single semantic_view string
    fqn = env.get("semantic_view", "")
    short = env.get("semantic_view_short", fqn.split(".")[-1] if fqn else "")
    return [{"fqn": fqn, "short_name": short}] if fqn else []


def get_agents(environment: str = "dev") -> list:
    """Return list of agent dicts for an environment.

    New format returns the list directly. Old format wraps the single entry.
    Each dict has: {"fqn": "...", "short_name": "...", "semantic_views": [...]}
    """
    config = load_config()
    env = config["environments"][environment]
    if _is_new_config_format(config):
        return env.get("agents", [])
    # Old format: single agent_name string
    fqn = env.get("agent_name", "")
    short = env.get("agent_short", fqn.split(".")[-1] if fqn else "")
    sv_fqn = env.get("semantic_view", "")
    return [{"fqn": fqn, "short_name": short, "semantic_views": [sv_fqn] if sv_fqn else []}] if fqn else []


@functools.lru_cache(maxsize=None)
def _load_thresholds_cached(inst: str) -> dict:
    return _read_yaml(os.path.join(inst, "config", "thresholds.yaml"))


def load_thresholds() -> dict:
    return _load_thresholds_cached(instance_dir())


def get_llm_model(role: str = "model") -> str:
    config = load_config()
    llm_config = config.get("llm", {})
    return llm_config.get(role, llm_config.get("model", "claude-opus-4-7"))


def question_bank_dir(bank_type: str) -> str:
    """Resolve a question-bank directory from instance config (falls back to the
    conventional layout). bank_type is 'agent' or 'semantic_view'."""
    qb = load_config().get("question_banks", {})
    key = "agent_dir" if bank_type == "agent" else "semantic_view_dir"
    rel = qb.get(key, os.path.join("question_banks", bank_type))
    return instance_path(rel)


def load_question_bank(bank_type: str, difficulty: str) -> list:
    path = os.path.join(question_bank_dir(bank_type), f"{difficulty}_questions.yaml")
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("questions", [])


def current_role(conn: snowflake.connector.SnowflakeConnection) -> str:
    """Return the session's current role.

    Used by account discovery (discover_account.py) to label how complete the
    discovered inventory is, since SHOW ... IN ACCOUNT only returns objects the
    running role can see. Falls back to 'UNKNOWN' on any error.
    """
    rows = execute_sql(conn, "SELECT CURRENT_ROLE() AS ROLE")
    if rows and "error" not in rows[0]:
        return rows[0].get("ROLE") or rows[0].get("role") or "UNKNOWN"
    return "UNKNOWN"


def build_credits_expr(
    pricing: dict,
    input_col: str = "input_tokens",
    output_col: str = "output_tokens",
    cache_col: str = "cache_read_tokens",
) -> str:
    """Cache-aware per-model credit CASE expression built from the pricing config.

    Charges non-cache input at the input rate, cache-read input at the (much
    cheaper) cache_read rate, and output at the output rate. Falls back to the
    input rate for cache reads when a model has no cache_read rate. GREATEST
    guards against cache_read exceeding input. This is the single source of the
    credit formula for the Python-built monitoring SQL (bootstrap + example seed).
    """
    default_in = pricing.get("default_input_credits_per_million", 1.0)
    default_out = pricing.get("default_output_credits_per_million", 1.0)

    def term(in_r, out_r, cache_r):
        return (
            f"GREATEST(COALESCE({input_col},0)-COALESCE({cache_col},0),0)/1000000.0*{in_r} "
            f"+ COALESCE({cache_col},0)/1000000.0*{cache_r} "
            f"+ COALESCE({output_col},0)/1000000.0*{out_r}"
        )

    parts = []
    for model, rates in pricing.get("models", {}).items():
        in_r = rates["input_credits_per_million"]
        out_r = rates["output_credits_per_million"]
        cache_r = rates.get("cache_read_credits_per_million", in_r)
        parts.append(f"WHEN model_used = '{model}' THEN {term(in_r, out_r, cache_r)}")
    parts.append(f"ELSE {term(default_in, default_out, default_in)}")
    return "CASE " + " ".join(parts) + " END"


def execute_sql(conn: snowflake.connector.SnowflakeConnection, sql: str) -> list:
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        return [{"error": str(e)}]


def call_cortex_agent(
    conn: snowflake.connector.SnowflakeConnection,
    agent_name: str,
    question: str
) -> dict:
    parts = agent_name.split(".")
    if len(parts) != 3:
        return {"error": f"Invalid agent name: {agent_name}"}
    database, schema, name = parts

    token = conn.rest.token
    host = conn.host.replace("_", "-").lower()

    url = f"https://{host}/api/v2/databases/{database}/schemas/{schema}/agents/{name}:run"
    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120, stream=True)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        text_parts = []
        sql_stmt = ""
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event: error"):
                next_line = next(resp.iter_lines(decode_unicode=True), "")
                if next_line.startswith("data:"):
                    try:
                        err = json.loads(next_line[5:].strip())
                        return {"error": err.get("message", "Unknown error")}
                    except json.JSONDecodeError:
                        pass
                return {"error": "Agent returned error event"}
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                event = json.loads(data)
                if "message" in event and "code" in event:
                    return {"error": event["message"]}
                if "text" in event:
                    if event.get("text"):
                        text_parts.append(event["text"])
                if "content" in event:
                    for item in event.get("content", []):
                        if isinstance(item, dict) and item.get("type") == "tool_results":
                            tool_content = item.get("tool_results", {}).get("content", [])
                            for tc in tool_content:
                                if isinstance(tc, dict) and tc.get("type") == "json":
                                    sql_stmt = sql_stmt or tc.get("json", {}).get("sql", "")
            except json.JSONDecodeError:
                pass

        result = {"content": []}
        if text_parts:
            result["content"].append({"type": "text", "text": "".join(text_parts)})
        if sql_stmt:
            result["content"].append({"type": "sql", "statement": sql_stmt})
        return result

    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def call_cortex_analyst(
    conn: snowflake.connector.SnowflakeConnection,
    semantic_view: str,
    question: str,
) -> dict:
    """Call Cortex Analyst via the REST message API (non-deprecated path).

    Mirrors call_cortex_agent's auth/host derivation. Returns
    {"content": [...]} on success or {"error": "..."} on failure.
    """
    token = conn.rest.token
    host = conn.host.replace("_", "-").lower()

    url = f"https://{host}/api/v2/cortex/analyst/message"
    headers = {
        "Authorization": f'Snowflake Token="{token}"',
        "Content-Type": "application/json",
    }
    payload = {
        "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
        "semantic_view": semantic_view,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        return {"content": data.get("message", {}).get("content", [])}
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}


def llm_complete(conn: snowflake.connector.SnowflakeConnection, model: str, prompt: str) -> str:
    escaped = prompt.replace("'", "''").replace("\\", "\\\\")
    sql = f"SELECT SNOWFLAKE.CORTEX.COMPLETE('{model}', '{escaped}') AS response"
    cursor = conn.cursor()
    cursor.execute(sql)
    result = cursor.fetchone()
    return result[0] if result else ""


def log_eval_run(
    conn: snowflake.connector.SnowflakeConnection,
    table: str,
    run_data: dict
):
    cols = list(run_data.keys())
    placeholders = []
    binds = []
    for col in cols:
        v = run_data[col]
        if isinstance(v, (dict, list)):
            placeholders.append("PARSE_JSON(%s)")   # VARIANT columns
            binds.append(json.dumps(v, default=str))
        else:
            placeholders.append("%s")
            binds.append(v)
    ev = get_framework_config()
    fqn = f"{ev['database']}.{ev['schema']}.{table}"
    sql = f"INSERT INTO {fqn} ({', '.join(cols)}) SELECT {', '.join(placeholders)}"
    conn.cursor().execute(sql, tuple(binds))


def format_results_table(results: list) -> str:
    if not results:
        return "No results"
    headers = list(results[0].keys())
    rows = [[str(row.get(h, "")) for h in headers] for row in results]
    widths = [max(len(h), max((len(r[i]) for r in rows), default=0)) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, widths))
    sep_line = "-+-".join("-" * w for w in widths)
    data_lines = [" | ".join(r[i].ljust(widths[i]) for i in range(len(headers))) for r in rows]
    return "\n".join([header_line, sep_line] + data_lines)
