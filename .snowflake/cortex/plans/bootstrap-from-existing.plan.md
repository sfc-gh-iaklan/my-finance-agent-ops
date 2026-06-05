# Plan: Bootstrap Framework from Existing Environment

## Context
The framework currently assumes a greenfield setup (create databases, RBAC, data tables from scratch). Customers already have semantic views and agents in their account. We need a "bootstrap" flow that:
1. Discovers what they already have
2. Asks them to pick which SVs/agents to govern
3. Asks for a single DB+schema where the framework will put its own tables
4. Generates a config file and creates only the framework's internal objects

## Design Decisions
- **Multi-object config**: The config will support lists of semantic views and agents (not just one pair)
- **DEV-only bootstrap**: Only the `dev` section is required; `prod` is a placeholder populated when CI/CD is set up
- **Framework section**: A `framework` key replaces the old `eval` key, with a user-provided DB+schema for all framework objects
- **Live discovery**: The CoCo skill runs SQL directly (no dependency on discover_account.py or Python)
- **Minimal setup SQL**: One script creates eval tables + monitoring tables + observability views in the user's chosen schema

## New Config Shape (environments.yaml)

```yaml
# Populated by the bootstrap skill
connection_name: JCHEN_AWS1   # or whatever their connection is

framework:
  database: CUSTOMER_OPS      # user-provided existing DB
  schema: AGENTOPS            # user-provided (skill creates if needed)
  warehouse: COMPUTE_WH       # user-provided existing warehouse

environments:
  dev:
    semantic_views:
      - fqn: MY_DB.ANALYTICS.SALES_SV
        short_name: SALES_SV
      - fqn: MY_DB.ANALYTICS.SUPPORT_SV
        short_name: SUPPORT_SV
    agents:
      - fqn: MY_DB.ANALYTICS.SALES_AGENT
        short_name: SALES_AGENT
        semantic_views: [MY_DB.ANALYTICS.SALES_SV]  # resolved from DESCRIBE
      - fqn: MY_DB.ANALYTICS.SUPPORT_AGENT
        short_name: SUPPORT_AGENT
        semantic_views: [MY_DB.ANALYTICS.SUPPORT_SV]

  prod:  # populated later for CI/CD
    semantic_views: []
    agents: []

question_banks:
  agent_dir: question_banks/agent
  semantic_view_dir: question_banks/semantic_view
```

## Task Breakdown

### 1. Design new config format
- Define the YAML schema above
- Ensure backwards compatibility note (old format still loads or error message guides migration)
- Write the template file

### 2. Create framework-only setup SQL
A single SQL script that creates (in `{{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}`):
- `SEMANTIC_VIEW_EVAL_RUNS` — existing eval results table
- `SEMANTIC_VIEW_EVAL_DETAILS` — existing eval detail table
- `USER_FEEDBACK` — from 07_monitoring_tables.sql
- `SCHEDULED_EVAL_RUNS` — from 07_monitoring_tables.sql
- `USAGE_METRICS` — from 07_monitoring_tables.sql
- `HEALTH_CHECK_RESULTS` — from 07_monitoring_tables.sql
- `ALERT_HISTORY` — from 07_monitoring_tables.sql
- Observability views (from 05_observability_setup.sql)
- Monitoring views (from 09_monitoring_views.sql)

No RBAC. No warehouse creation. No data tables.

### 3. Write the CoCo bootstrap skill
The skill instructs Cortex Code to:

**Step 1 — Discovery**
```sql
SHOW SEMANTIC VIEWS IN ACCOUNT;
SHOW AGENTS IN ACCOUNT;
SHOW DATABASES;
```
Present results to user.

**Step 2 — Selection**
Ask user (via ask_user_question):
- Which semantic views to govern (multi-select)
- Which agents to govern (multi-select)
- For each selected agent, DESCRIBE AGENT to resolve its bound SVs

**Step 3 — Framework location**
Ask user:
- Database for framework objects (text input, suggest from discovered DBs)
- Schema name (text input, default: `AGENTOPS`)
- Warehouse to use (text input)

**Step 4 — Generate config**
Write `instance/config/environments.yaml` with populated values.

**Step 5 — Run setup SQL**
Execute the framework-only setup script against the chosen DB.SCHEMA.

### 4. Extend discover_account.py
Add `list_databases(conn)` that returns SHOW DATABASES results. Minor enhancement — not critical since the skill does its own SQL, but keeps the Python path consistent.

### 5. Update utils.py for new config shape
- `load_config()` should handle both old (single SV/agent) and new (list) formats
- Add helpers: `get_semantic_views(environment)`, `get_agents(environment)`
- Existing callers that use `config["environments"]["dev"]["semantic_view"]` need a migration path (read first item from list, or fail with clear message)

## Files to Create/Modify

| File | Action |
|------|--------|
| `instance/config/environments.yaml.template` | **Rewrite** with new multi-object format |
| `setup/00_framework_tables.sql` | **New** — minimal framework-only setup |
| `.cortex/skills/bootstrap-from-existing.md` | **New** — the CoCo skill |
| `evaluation/utils.py` | **Modify** — support new config shape |
| `evaluation/discover_account.py` | **Minor modify** — add database listing |

## Out of Scope
- RBAC setup (not needed for bootstrap)
- Warehouse creation (customer has one)
- Data table creation (customer's data already exists)
- CI/CD workflow changes (those still work with the prod section when populated later)
- Monitoring tasks/alerts creation (can be added as a follow-up)
