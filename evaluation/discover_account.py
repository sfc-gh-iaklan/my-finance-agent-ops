"""
discover_account.py
Account discovery for customer onboarding (issue #30).

Discovers the Cortex Agents visible to the running role, and for each agent
resolves the chain:

    agent -> orchestration model -> tool types -> bound semantic view(s) -> warehouse

by parsing the ``agent_spec`` JSON returned by ``DESCRIBE AGENT``. It also lists
the semantic views visible in the account and flags which ones are bound to a
discovered agent.

This is a DISCOVERY AID, not a guarantee of completeness. ``SHOW ... IN ACCOUNT``
only returns objects the *running role* can see, so the output is explicitly
labelled with the visibility scope (the running role) and only claims account
completeness when run as ACCOUNTADMIN. The parser is deliberately defensive:
multi-tool agents, non-semantic-view agents, custom/external tools, name
collisions and ``agent_spec`` shape drift across releases are all handled by
labelling rather than crashing.

Designed to be imported by the onboarding notebook (issue #29):

    from discover_account import build_inventory
    inv = build_inventory(conn)

or run standalone:

    python discover_account.py                    # table to stdout (dev connection)
    python discover_account.py --format json
    python discover_account.py --output inventory.json
    python discover_account.py --environment prod
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from utils import get_connection, execute_sql, current_role, format_results_table


# Tool types we know how to reason about. Anything else is surfaced as a note
# ("unsupported — monitoring only") rather than treated as an error, so new or
# custom tool types never break discovery.
KNOWN_TOOL_TYPES = {
    "cortex_analyst_text_to_sql",
    "cortex_search",
    "sql_exec",
    "data_to_chart",
}


def _is_error(rows: list) -> bool:
    """execute_sql returns [{"error": "..."}] on failure; detect that shape."""
    return bool(rows) and isinstance(rows[0], dict) and "error" in rows[0] and len(rows[0]) == 1


def _error_message(rows: list) -> str:
    return rows[0].get("error", "unknown error") if rows else "no rows returned"


def _cval(row: dict, *keys: str):
    """Case-insensitive column lookup.

    SHOW/DESCRIBE result column names vary in case across drivers, so try each
    requested key as-is, upper, and lower before giving up.
    """
    for key in keys:
        for variant in (key, key.upper(), key.lower()):
            if variant in row:
                return row[variant]
    return None


def _fqn(row: dict) -> str:
    """Build a fully-qualified name from a SHOW row (database.schema.name)."""
    db = _cval(row, "database_name") or ""
    schema = _cval(row, "schema_name") or ""
    name = _cval(row, "name") or ""
    return ".".join(p for p in (db, schema, name) if p)


# ---------------------------------------------------------------------------
# Raw inventory queries
# ---------------------------------------------------------------------------
def list_agents(conn) -> list:
    """Agents visible to the running role. Returns [] on error (caller checks notes)."""
    rows = execute_sql(conn, "SHOW AGENTS IN ACCOUNT")
    if _is_error(rows):
        return []
    return rows


def list_semantic_views(conn) -> list:
    """Semantic views visible to the running role. Returns [] on error."""
    rows = execute_sql(conn, "SHOW SEMANTIC VIEWS IN ACCOUNT")
    if _is_error(rows):
        return []
    return rows


def list_databases(conn) -> list:
    """Databases visible to the running role. Returns [] on error."""
    rows = execute_sql(conn, "SHOW DATABASES")
    if _is_error(rows):
        return []
    return rows


def list_warehouses(conn) -> list:
    """Warehouses visible to the running role. Returns [] on error."""
    rows = execute_sql(conn, "SHOW WAREHOUSES")
    if _is_error(rows):
        return []
    return rows


def describe_agent(conn, agent_fqn: str) -> dict:
    """DESCRIBE AGENT for one agent; returns {"row": <raw>, "error": <str|None>}."""
    rows = execute_sql(conn, f"DESCRIBE AGENT {agent_fqn}")
    if _is_error(rows):
        return {"row": None, "error": _error_message(rows)}
    if not rows:
        return {"row": None, "error": "DESCRIBE AGENT returned no rows"}
    return {"row": rows[0], "error": None}


# ---------------------------------------------------------------------------
# Defensive agent_spec parsing
# ---------------------------------------------------------------------------
def parse_agent_spec(spec, agent_fqn: str) -> dict:
    """Extract the model -> tools -> semantic view -> warehouse chain.

    ``spec`` may be a JSON string (as returned by DESCRIBE AGENT) or an already
    parsed dict. Every field is read with .get() fallbacks; any shape surprise
    appends a human-readable note instead of raising.
    """
    record = {
        "agent_fqn": agent_fqn,
        "model": "UNKNOWN",
        "tool_types": [],
        "semantic_views": [],
        "warehouses": [],
        "pillar1_applicable": False,
        "notes": [],
    }

    if isinstance(spec, str):
        try:
            spec = json.loads(spec)
        except (json.JSONDecodeError, TypeError):
            record["notes"].append("Could not parse agent_spec JSON; agent left unresolved.")
            return record
    if not isinstance(spec, dict):
        record["notes"].append("agent_spec is not an object; agent left unresolved.")
        return record

    # Orchestration model.
    model = (spec.get("models") or {}).get("orchestration")
    if model:
        record["model"] = model
    else:
        record["notes"].append("No orchestration model found in agent_spec.")

    # Tools (a list of {"tool_spec": {"type", "name"}}).
    tools = spec.get("tools")
    tool_name_to_type = {}
    if isinstance(tools, list):
        for tool in tools:
            spec_block = (tool or {}).get("tool_spec") or {}
            ttype = spec_block.get("type") or "unknown"
            tname = spec_block.get("name")
            record["tool_types"].append(ttype)
            if tname:
                tool_name_to_type[tname] = ttype
            if ttype not in KNOWN_TOOL_TYPES:
                record["notes"].append(
                    f"Tool '{tname or ttype}' has unsupported type '{ttype}' — monitoring only."
                )
    elif tools is not None:
        record["notes"].append("agent_spec.tools is not a list; tools left unresolved.")

    # Tool resources: bound semantic view(s) + execution warehouse, keyed by tool name.
    resources = spec.get("tool_resources")
    if isinstance(resources, dict):
        for tool_name, res in resources.items():
            if not isinstance(res, dict):
                continue
            sv = res.get("semantic_view")
            if sv:
                record["semantic_views"].append(sv)
            wh = ((res.get("execution_environment") or {}).get("warehouse"))
            if wh:
                record["warehouses"].append(wh)
    elif resources is not None:
        record["notes"].append("agent_spec.tool_resources is not an object; resources left unresolved.")

    # De-duplicate while preserving order.
    record["semantic_views"] = list(dict.fromkeys(record["semantic_views"]))
    record["warehouses"] = list(dict.fromkeys(record["warehouses"]))

    record["pillar1_applicable"] = len(record["semantic_views"]) > 0
    if not record["pillar1_applicable"]:
        record["notes"].append(
            "No semantic view bound — Pillar 1 (semantic-view audit) is N/A for this agent."
        )

    return record


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def build_inventory(conn) -> dict:
    """Discover agents + semantic views visible to the running role and resolve
    the agent -> SV -> warehouse -> model chain for each agent.

    Returns a structured dict (JSON-serialisable) with an explicit visibility
    scope. Never raises on per-agent issues — they are captured as notes.
    """
    role = current_role(conn)
    account_complete = role.upper() == "ACCOUNTADMIN"

    inventory = {
        "visibility_scope": {
            "role": role,
            "account_complete": account_complete,
            "note": (
                "Inventory is complete for the account."
                if account_complete
                else f"Inventory is scoped to objects visible to role '{role}'. "
                "Run as ACCOUNTADMIN for an account-complete view."
            ),
        },
        "agents": [],
        "semantic_views_in_account": [],
        "summary": {},
    }

    # Semantic views in the account (independent of agents).
    sv_rows = list_semantic_views(conn)
    sv_catalog = []
    for row in sv_rows:
        sv_catalog.append({
            "semantic_view_fqn": _fqn(row),
            "owner": _cval(row, "owner"),
            "comment": _cval(row, "comment"),
            "bound_to_agent": False,
        })

    # Agents + per-agent chain resolution.
    agent_rows = list_agents(conn)
    bound_svs = set()
    for row in agent_rows:
        agent_fqn = _fqn(row)
        desc = describe_agent(conn, agent_fqn)
        if desc["error"]:
            inventory["agents"].append({
                "agent_fqn": agent_fqn,
                "owner": _cval(row, "owner"),
                "model": "UNKNOWN",
                "tool_types": [],
                "semantic_views": [],
                "warehouses": [],
                "pillar1_applicable": False,
                "notes": [f"DESCRIBE AGENT failed: {desc['error']}"],
            })
            continue

        record = parse_agent_spec(_cval(desc["row"], "agent_spec"), agent_fqn)
        record["owner"] = _cval(row, "owner")
        inventory["agents"].append(record)
        bound_svs.update(record["semantic_views"])

    # Cross-reference: mark which catalog SVs are bound to a discovered agent.
    for sv in sv_catalog:
        if sv["semantic_view_fqn"] in bound_svs:
            sv["bound_to_agent"] = True
    inventory["semantic_views_in_account"] = sv_catalog

    # Semantic views referenced by an agent but not visible in the catalog
    # (e.g. owned by a role we cannot see) — surface as a discovery caveat.
    catalog_fqns = {sv["semantic_view_fqn"] for sv in sv_catalog}
    unseen = sorted(bound_svs - catalog_fqns)

    inventory["summary"] = {
        "agents_discovered": len(inventory["agents"]),
        "agents_with_semantic_view": sum(1 for a in inventory["agents"] if a["pillar1_applicable"]),
        "semantic_views_visible": len(sv_catalog),
        "semantic_views_bound": len(bound_svs),
        "semantic_views_bound_but_not_visible": unseen,
        "agents_with_notes": sum(1 for a in inventory["agents"] if a["notes"]),
    }
    return inventory


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------
def print_report(inventory: dict):
    scope = inventory["visibility_scope"]
    summary = inventory["summary"]

    print(f"\n{'=' * 78}")
    print("ACCOUNT DISCOVERY — Cortex Agents & Semantic Views")
    print(f"{'=' * 78}")
    print(f"Visibility role:        {scope['role']}")
    print(f"Account-complete:       {scope['account_complete']}")
    print(f"  {scope['note']}")
    print(f"{'-' * 78}")
    print(f"Agents discovered:      {summary['agents_discovered']}")
    print(f"  with semantic view:   {summary['agents_with_semantic_view']}")
    print(f"  with caveats/notes:   {summary['agents_with_notes']}")
    print(f"Semantic views visible: {summary['semantic_views_visible']}")
    print(f"  bound to an agent:    {summary['semantic_views_bound']}")
    if summary["semantic_views_bound_but_not_visible"]:
        print("  bound but NOT visible to this role:")
        for fqn in summary["semantic_views_bound_but_not_visible"]:
            print(f"    - {fqn}")
    print(f"{'=' * 78}")

    if inventory["agents"]:
        agent_table = [{
            "AGENT": a["agent_fqn"],
            "MODEL": a["model"],
            "TOOLS": ", ".join(a["tool_types"]) or "-",
            "SEMANTIC_VIEW(S)": ", ".join(a["semantic_views"]) or "N/A",
            "WAREHOUSE(S)": ", ".join(a["warehouses"]) or "-",
            "PILLAR1": "yes" if a["pillar1_applicable"] else "N/A",
        } for a in inventory["agents"]]
        print("\nAGENTS")
        print(format_results_table(agent_table))

        notes = [(a["agent_fqn"], n) for a in inventory["agents"] for n in a["notes"]]
        if notes:
            print("\nNOTES")
            for fqn, note in notes:
                print(f"  [{fqn}] {note}")

    if inventory["semantic_views_in_account"]:
        sv_table = [{
            "SEMANTIC_VIEW": sv["semantic_view_fqn"],
            "OWNER": sv["owner"] or "-",
            "BOUND_TO_AGENT": "yes" if sv["bound_to_agent"] else "no",
        } for sv in inventory["semantic_views_in_account"]]
        print("\nSEMANTIC VIEWS")
        print(format_results_table(sv_table))


def main():
    parser = argparse.ArgumentParser(
        description="Discover Cortex Agents + semantic views visible to the running role"
    )
    parser.add_argument("--environment", "-e", default="dev", choices=["dev", "prod"],
                        help="Which instance environment's connection to use")
    parser.add_argument("--format", choices=["table", "json"], default="table",
                        help="stdout format when --output is not given")
    parser.add_argument("--output", "-o", default="", help="Write the inventory JSON to this path")
    args = parser.parse_args()

    conn = get_connection(args.environment)
    try:
        inventory = build_inventory(conn)
    finally:
        conn.close()

    if args.output:
        with open(args.output, "w") as f:
            json.dump(inventory, f, indent=2, default=str)
        print(f"Inventory written to {args.output}")
        print_report(inventory)
    elif args.format == "json":
        print(json.dumps(inventory, indent=2, default=str))
    else:
        print_report(inventory)

    # Discovery is an aid, never a gate — always succeed.
    sys.exit(0)


if __name__ == "__main__":
    main()
