# Snowflake AgentOps Framework

An end-to-end framework for developing, testing, and promoting **Semantic Views** and **Cortex Agents** in Snowflake with CI/CD-driven governance.

Built for data teams who want to **self-serve semantic view development** while maintaining production-grade quality gates.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DEVELOPMENT WORKFLOW                         │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │ Snowsight │    │  CoCo /  │    │   Git    │    │   GitHub     │  │
│  │  (Edit)   │───▶│  IDE     │───▶│ Commit   │───▶│   Actions    │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────┬───────┘  │
│                                                          │          │
│                                                          ▼          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    CI PIPELINE (on PR)                        │   │
│  │                                                               │   │
│  │  ┌─────────────────────────────────────────────────────────┐  │   │
│  │  │ LAYER 1: AUDITS (structural quality gate)               │  │   │
│  │  │                                                         │  │   │
│  │  │  Semantic View Audit:                                   │  │   │
│  │  │  ├─ Documentation (descriptions, comments)              │  │   │
│  │  │  ├─ Naming conventions (casing, special chars)          │  │   │
│  │  │  ├─ Metadata completeness (VALUES, types)               │  │   │
│  │  │  ├─ Relationships (coverage, validity)                  │  │   │
│  │  │  ├─ Inconsistencies (conflicting definitions)           │  │   │
│  │  │  └─ Duplicates (redundant descriptions)                 │  │   │
│  │  │                                                         │  │   │
│  │  │  Agent Native Evaluation (EXECUTE_AI_EVALUATION):       │  │   │
│  │  │  ├─ answer_correctness (semantic match)                 │  │   │
│  │  │  ├─ logical_consistency (reasoning coherence)           │  │   │
│  │  │  └─ safety (custom LLM-judged metric)                   │  │   │
│  │  └─────────────────────────────────────────────────────────┘  │   │
│  │                              │                                 │   │
│  │                              ▼                                 │   │
│  │  ┌─────────────────────────────────────────────────────────┐  │   │
│  │  │ LAYER 2: QUESTION BANK EVALUATION (accuracy gate)       │  │   │
│  │  │                                                         │  │   │
│  │  │  Semantic View:                                         │  │   │
│  │  │  ┌────────┐  ┌──────────┐  ┌───────────┐               │  │   │
│  │  │  │  Easy  │  │   Hard   │  │ Ambiguous │               │  │   │
│  │  │  └────────┘  └──────────┘  └───────────┘               │  │   │
│  │  │                                                         │  │   │
│  │  │  Agent (Native GPA via EXECUTE_AI_EVALUATION):          │  │   │
│  │  │  ┌────────────┐  ┌─────────────┐  ┌─────────────┐      │  │   │
│  │  │  │ Answerable │  │Out of Scope │  │ Adversarial │      │  │   │
│  │  │  └────────────┘  └─────────────┘  └─────────────┘      │  │   │
│  │  └─────────────────────────────────────────────────────────┘  │   │
│  │                                                               │   │
│  │  Post combined results to PR comment                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                    accuracy >= threshold?                            │
│                         │          │                                 │
│                        YES        NO ──▶ Block merge, iterate       │
│                         │                                           │
│                         ▼                                           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    CD PIPELINE (on merge)                     │   │
│  │  Audit gate ──▶ Final eval ──▶ Deploy to PROD ──▶ Log       │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- A Snowflake account with Cortex AI features enabled
- A named connection in `~/.snowflake/connections.toml` (or env vars `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PASSWORD`)
- [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code) (recommended for guided setup)

### Setup with Cortex Code (Recommended)

Open this repo in Cortex Code and invoke the bootstrap skill:

```
/bootstrap-from-existing
```

The skill will interactively:
1. Discover your existing semantic views and agents
2. Let you select which to bring under governance
3. Ask for a database + schema to store framework tables
4. Generate your `instance/config/environments.yaml`
5. Execute the setup SQL to create framework objects

### Manual Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy config templates:
```bash
cd instance/config
cp environments.yaml.template environments.yaml
cp thresholds.yaml.template thresholds.yaml
cp monitoring.yaml.template monitoring.yaml
cp schedules.yaml.template schedules.yaml
```

3. Edit `instance/config/environments.yaml` — replace all `{{TOKEN}}` placeholders with your values.

4. Execute each SQL script in `setup/` against your Snowflake account (in order: 01, 04, 05, 07, 08, 09, 10, 11), substituting the tokens with your config values.

5. Add your semantic view YAML to `instance/semantic_views/dev/` and agent SQL to `instance/agents/dev/`.

---

## Directory Structure

```
Snowflake_AgentOps_Framework/
├── .cortex/skills/                     # Cortex Code skills for guided setup
│   └── bootstrap-from-existing.md    # Bootstrap from existing Snowflake environment
├── .github/workflows/                  # CI/CD pipelines
│   ├── semantic_view_ci.yml            # On PR: audit → evaluate → comment
│   ├── semantic_view_cd.yml            # On merge: audit gate → eval → promote
│   ├── agent_ci.yml                    # On PR: native GPA eval → comment
│   └── agent_cd.yml                   # On merge: native GPA eval gate → promote
├── config/
│   └── defaults.yaml                  # Universal defaults: LLM models + credit pricing
├── docs/                              # Reference & explanation docs
│   ├── README.md                      # Documentation index
│   ├── explanation/                   # Design & intent
│   └── reference/                     # Lookup-style: cost model
├── evaluation/                         # Evaluation engine (config-driven)
│   ├── audit_semantic_view.py          # Best practices audit (naming, docs, metadata)
│   ├── audit_agent.py                  # Native EXECUTE_AI_EVALUATION (GPA framework)
│   ├── evaluate_semantic_view.py       # Batch SV evaluation (SQL comparison + LLM judge)
│   ├── llm_judge.py                   # LLM-as-a-Judge for SV evaluation
│   ├── discover_account.py            # Account discovery: agents, SVs, tools, warehouses
│   ├── generate_question_bank.py      # Starter question-bank generator
│   ├── adversarial_library.yaml       # Curated adversarial attack patterns
│   └── utils.py                       # Instance resolver + Snowflake helpers
├── instance/                           # YOUR WORKSPACE (populated by CoCo skill or manually)
│   ├── config/
│   │   ├── environments.yaml.template  # Project config template
│   │   ├── thresholds.yaml.template    # Accuracy thresholds template
│   │   ├── monitoring.yaml.template    # Alert thresholds template
│   │   └── schedules.yaml.template     # Task schedules template
│   ├── semantic_views/{dev,prod}/      # Your semantic view YAML files
│   ├── agents/{dev,prod}/              # Your agent SQL files
│   └── question_banks/                 # Your question banks
│       ├── semantic_view/              # Easy, hard, ambiguous questions
│       └── agent/                      # Answerable, out-of-scope, adversarial
├── monitoring/                         # Health check & monitoring
│   ├── dashboard.py                   # Streamlit in Snowflake monitoring dashboard
│   ├── health_check.py               # Health checks (7 checks)
│   ├── cost_reconcile.py             # Reconcile estimated vs actual AI Credits
│   ├── snowflake.yml.template         # SiS deploy descriptor
│   └── pyproject.toml                 # SiS package dependencies
├── setup/                              # Snowflake setup SQL
│   ├── 00_framework_tables.sql        # All framework objects (tables, views, alerts, tasks)
│   └── deploy.py                      # Deploy SV/agent to an env (used by CI)
├── .gitignore
├── AGENT.md                           # CoCo agent instructions
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
├── README.md                          # This file
├── architecture.html
└── requirements.txt
```

---

## Evaluation Pipeline (Two Layers)

### Layer 1: Audits (Structural Quality)

**Semantic View Best Practices Audit** (`audit_semantic_view.py`):

| Check | Description | Severity |
|-------|-------------|----------|
| Documentation | All tables/columns have descriptions | WARNING |
| Naming | No special characters, consistent casing | WARNING/INFO |
| Metadata | VALUES on categorical columns, data types | WARNING |
| Relationships | Sufficient coverage for table count | ERROR/WARNING |
| Inconsistencies | Conflicting metric/filter definitions | CRITICAL/HIGH |
| Duplicates | Redundant descriptions across columns | MEDIUM |

**Agent Native Evaluation (GPA Framework)** (`audit_agent.py`):

| Metric | Type | Description |
|--------|------|-------------|
| `answer_correctness` | Built-in | Semantic match against ground truth |
| `logical_consistency` | Built-in | Internal reasoning coherence |
| `safety` | Custom LLM-judged | Scope/boundary compliance |
| `groundedness` | Custom LLM-judged | Claims supported by tool outputs |
| `execution_efficiency` | Custom LLM-judged | Optimal tool selection |
| `answer_relevance` | Custom LLM-judged | Response addresses the question |
| `conciseness` | Custom LLM-judged | No unnecessary verbosity |
| `pii_leakage` | Custom LLM-judged | No PII exposed |

### Layer 2: Question Bank Evaluation (Accuracy)

**Semantic View** (`evaluate_semantic_view.py`):

| Category | Evaluation Method | Threshold (PROD) |
|----------|-------------------|-------------------|
| Easy | SQL result comparison + LLM judge | 95% |
| Hard | SQL result comparison + LLM judge | 75% |
| Ambiguous | LLM-as-a-Judge only | 60% |

**Agent** (native GPA evaluation):

| Category | Focus |
|----------|-------|
| Answerable | Data queries + correctness |
| Out of Scope | Boundary testing |
| Adversarial | Prompt injection, data exfiltration |

---

## CI/CD Pipeline Flow

### Semantic View (PR → Merge → PROD)

```
PR Opened (touching instance/semantic_views/)
  │
  ├── Job 1: Best Practices Audit
  │   └── audit_semantic_view.py (structural checks)
  │
  └── Job 2: Question Bank Evaluation
      ├── Deploy SV to DEV
      ├── evaluate_semantic_view.py --environment dev
      └── Post combined results as PR comment
           │
   Merge to main
           │
           ├── audit_semantic_view.py (gate: fail = block deploy)
           ├── evaluate_semantic_view.py (gate: accuracy >= threshold)
           └── Deploy to PROD
```

### Agent (PR → Merge → PROD)

```
PR Opened (touching instance/agents/)
  │
  └── Job 1: Native Snowflake GPA Evaluation
      ├── Deploy agent to DEV
      └── audit_agent.py (EXECUTE_AI_EVALUATION with GPA metrics)
           │
      Post results as PR comment
           │
   Merge to main
           │
           ├── audit_agent.py (native GPA eval gate)
           └── Deploy to PROD
```

---

## Run Evaluations Locally

```bash
# SV best practices audit
python evaluation/audit_semantic_view.py \
  --environment dev \
  --output sv_audit.json

# SV question bank evaluation (~5 min)
python evaluation/evaluate_semantic_view.py \
  --environment dev \
  --output sv_eval.json

# Agent native GPA evaluation (~8 min)
python evaluation/audit_agent.py \
  --environment dev \
  --output agent_eval.json

# Discover agents and semantic views in your account
python evaluation/discover_account.py --format json

# Generate a starter question bank from your semantic view
python evaluation/generate_question_bank.py
```

---

## Monitoring & Observability

The framework includes a full monitoring layer for long-term tracking of agent health, accuracy trends, user feedback, and cost.

### Automated Schedules

| Schedule | What |
|----------|------|
| Daily 02:00 UTC | Token usage & cost aggregation |
| Daily 02:15 UTC | Feedback sentiment analysis |
| Daily 02:30 UTC | Interaction quality scan |
| Daily 06:00 UTC | Health checks |
| Sunday 04:00 UTC | SV smoke test |
| Sunday 05:00 UTC | Agent smoke test |

### Alerts

| Alert | Trigger |
|-------|---------|
| Negative Feedback Spike | >25% negative feedback |
| Accuracy Regression | >10% accuracy drop |
| Latency Degradation | P95 > 30s |
| Cost Anomaly | Daily > 2x 7-day average |
| Error Spike | Error rate > 10% |
| Health Failure | Any UNHEALTHY check |
| Interaction Quality | >20% flagged or CRITICAL |

### Monitoring Dashboard

Deploy the Streamlit in Snowflake dashboard:

```bash
cd monitoring && snow streamlit deploy --replace
```

---

## Configuring Thresholds

Edit `instance/config/thresholds.yaml` to adjust quality gates per environment:

```yaml
semantic_view:
  prod:
    accuracy_threshold: 85
    easy_min_accuracy: 95
    hard_min_accuracy: 75
    ambiguous_min_accuracy: 60

agent:
  prod:
    accuracy_threshold: 85
    adversarial_min_accuracy: 98
```

---

## GitHub Actions Secrets Required

| Secret | Description |
|--------|-------------|
| `SNOWFLAKE_ACCOUNT` | Snowflake account identifier |
| `SNOWFLAKE_USER` | Service account username |
| `SNOWFLAKE_PASSWORD` | Service account password |
| `SNOWFLAKE_CONNECTION_NAME` | Named connection (optional) |

---

## Documentation

| Document | Type | What it covers |
|----------|------|----------------|
| [docs/README.md](docs/README.md) | Index | Documentation map |
| [Cost model](docs/reference/cost-model.md) | Reference | Evaluation cost in AI Credits |
| [Input governance](docs/explanation/pillar-1-input-governance.md) | Explanation | Semantic view audit design |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch → PR → merge workflow and commit conventions.

## License

Licensed under the [Apache License 2.0](LICENSE) (see also [NOTICE](NOTICE)).
