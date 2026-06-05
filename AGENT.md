# Snowflake AgentOps Framework - Agent Instructions

## Project Overview

This is an end-to-end framework for developing, testing, promoting, and monitoring **Semantic Views** and **Cortex Agents** in Snowflake. It targets data teams who want to self-serve semantic view development while maintaining production-grade quality gates via CI/CD.

This repo contains the **framework only** — no demo data, seed scripts, or bootstrap runner. Users configure their own instance via the `.cortex/skills/` or manually.

## Conventions

- Always ask the user when unsure or when design decisions are needed
- Always plan and document the plan before starting any work
- Write all code to files so everything is reproducible (no ephemeral snippets)
- All SQL follows Snowflake SQL syntax
- Python scripts use `snowflake-connector-python` and connect via named connections
- YAML is used for configuration (environments, thresholds, question banks, monitoring)
- GitHub Actions for CI/CD

## Snowflake Environment

The framework creates three databases per project (configured in `instance/config/environments.yaml`):

| Resource | Pattern |
|----------|---------|
| DEV database | `<PROJECT>_DEV` |
| PROD database | `<PROJECT>_PROD` |
| Eval database | `<PROJECT>_EVAL` |
| Schemas per env | `ANALYTICS` (tables), `SEMANTIC` (SV, agents, eval datasets) |
| Monitoring schema | `<PROJECT>_EVAL.MONITORING` |
| Observability schema | `<PROJECT>_EVAL.OBSERVABILITY` |
| Results schema | `<PROJECT>_EVAL.RESULTS` |
| Warehouse | `<PROJECT>_WH` (configurable size) |

### RBAC Roles

| Role | Purpose |
|------|---------|
| `<PROJECT>_ANALYST` | Create/edit SV in DEV, submit feedback, read results |
| `<PROJECT>_REVIEWER` | Inherits Analyst, read access across envs |
| `<PROJECT>_DEPLOYER` | Deploy SV/agents to DEV/PROD, write eval results, run tasks |
| `<PROJECT>_ADMIN` | Full access to everything |

Hierarchy: ANALYST → REVIEWER → ADMIN, DEPLOYER → ADMIN → SYSADMIN

## Promotion Path (2-tier)

```
Feature branch → PR (CI: deploy to DEV + evaluate) → Merge to main → CD: promote to PROD
```

## Directory Structure

```
Snowflake_AgentOps_Framework/
├── .cortex/skills/                     # Cortex Code skills for guided setup
│   └── bootstrap-from-existing.md    # Bootstrap from existing Snowflake environment
├── setup/                              # Snowflake setup SQL
│   ├── 00_framework_tables.sql        # All framework objects (tables, views, alerts, tasks)
│   └── deploy.py                      # Deploy SV/agent to an env (used by CI)
├── evaluation/                         # Evaluation engine (config-driven)
│   ├── audit_semantic_view.py          # Best practices audit
│   ├── audit_agent.py                  # Native EXECUTE_AI_EVALUATION (GPA)
│   ├── evaluate_semantic_view.py       # Batch SV eval with SQL comparison + LLM judge
│   ├── llm_judge.py                   # LLM-as-a-Judge
│   ├── discover_account.py            # Account discovery
│   ├── generate_question_bank.py      # Starter question-bank generator
│   ├── adversarial_library.yaml       # Curated adversarial patterns
│   └── utils.py                       # Instance resolver + SF helpers
├── monitoring/                         # Health check & monitoring
│   ├── dashboard.py                   # Streamlit in Snowflake dashboard
│   ├── health_check.py               # Health checks (7 checks)
│   ├── cost_reconcile.py             # Cost reconciliation
│   ├── snowflake.yml.template         # SiS deploy descriptor
│   └── pyproject.toml                 # SiS dependencies
├── instance/                           # USER WORKSPACE (populated via skill or manually)
│   ├── config/*.yaml.template         # Config templates with {{TOKEN}} placeholders
│   ├── semantic_views/{dev,prod}/     # User's semantic view YAML files
│   ├── agents/{dev,prod}/             # User's agent SQL files
│   └── question_banks/               # User's question banks
├── config/
│   └── defaults.yaml                  # Universal: LLM models + credit pricing
├── .github/workflows/                  # CI/CD pipelines
└── docs/                              # Reference & explanation docs
```

## Key Technical Patterns

### Instance Resolution

The active instance is set via the `AIOPS_INSTANCE` env var and defaults to `instance/` in the repo root. The `evaluation/utils.py` module resolves all paths relative to the active instance.

### Observability
- **Primary source**: `snowflake.local.ai_observability_events` (Snowflake's native AI observability view)
- No custom event table needed. Convenience views in `<PROJECT>_EVAL.OBSERVABILITY` wrap the native view.
- Key span names: `ReasoningAgentStepPlanning-N`, `CodingAgent.Step-N`, `SqlExecution_CortexAnalyst`, `Agent`, `AgentV2RequestResponseInfo`
- Token fields: `snow.ai.observability.agent.planning.token_count.{input,output,total,cache_read_input}`
- Agent identity: `snow.ai.observability.{database.name,schema.name,object.name,object.type}`

### Evaluation Pipeline (Two Layers)

**Layer 1 — Audits (structural quality gate):**
- `audit_semantic_view.py`: Parses YAML, checks documentation, naming, metadata, relationships, inconsistencies, duplicates. Severity-based pass/fail.
- `audit_agent.py`: Uses Snowflake's native `EXECUTE_AI_EVALUATION` with GPA framework metrics plus custom LLM-judged metrics. Configurable per environment via `thresholds.yaml`.

**Layer 2 — Question Bank Evaluation (accuracy gate):**
- `evaluate_semantic_view.py`: Calls Cortex Analyst, compares generated SQL results to ground truth, uses LLM judge for ambiguous questions.

### CI/CD (GitHub Actions)

| Workflow | Trigger | What |
|----------|---------|------|
| `semantic_view_ci.yml` | PR on `instance/semantic_views/` | Audit → eval on DEV → PR comment |
| `semantic_view_cd.yml` | Merge to main | Audit gate → eval on DEV → deploy to PROD |
| `agent_ci.yml` | PR on `instance/agents/` | Deploy to DEV → native GPA eval → PR comment |
| `agent_cd.yml` | Merge to main | Native GPA eval on DEV → deploy to PROD |

### Connection Pattern

Python scripts connect via named connection or env vars:
```python
import os, snowflake.connector
conn = snowflake.connector.connect(
    connection_name=os.getenv("SNOWFLAKE_CONNECTION_NAME") or "default"
)
```

### Configuration Files

The framework reads a merged config: universal **defaults** at the repo root, overlaid by the active **instance** (set via `AIOPS_INSTANCE`, default `instance/`).

- `config/defaults.yaml` — Universal: LLM model selection + Snowflake per-model credit pricing
- `instance/config/environments.yaml` — Per-env database, schema, warehouse, SV/agent names, paths
- `instance/config/thresholds.yaml` — Graduated accuracy thresholds (DEV → PROD)
- `instance/config/monitoring.yaml` — Alert thresholds, schedules, notifications
- `instance/config/schedules.yaml` — Task schedule profiles (demo/prod)

## GitHub Actions Secrets Required

| Secret | Description |
|--------|-------------|
| `SNOWFLAKE_ACCOUNT` | Snowflake account identifier |
| `SNOWFLAKE_USER` | Service account username |
| `SNOWFLAKE_PASSWORD` | Service account password |
| `SNOWFLAKE_CONNECTION_NAME` | Named connection (optional) |
