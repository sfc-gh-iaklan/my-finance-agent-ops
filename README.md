# Snowflake AgentOps Framework

A governance framework for **Semantic Views** and **Cortex Agents** in Snowflake. Clone this repo, point it at your existing agents, and get CI/CD quality gates, automated monitoring, and an App Runtime dashboard — without rebuilding your environment.

---

## What This Does

1. **Discovers** your existing semantic views and agents
2. **Evaluates** them with question banks + LLM-as-a-judge
3. **Monitors** accuracy, cost, latency, and interaction quality over time
4. **Gates** promotions via CI/CD pipelines (any CI system)
5. **Alerts** on regressions, feedback spikes, and cost anomalies

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DEVELOPMENT WORKFLOW                         │
│                                                                     │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐  │
│  │ Snowsight │    │  CoCo /  │    │   Git    │    │    CI/CD     │  │
│  │  (Edit)   │───▶│  IDE     │───▶│ Commit   │───▶│  Pipeline    │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────┬───────┘  │
│                                                          │          │
│                                                          ▼          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    CI PIPELINE (on PR)                        │   │
│  │                                                               │   │
│  │  ┌─────────────────────────────────────────────────────────┐  │   │
│  │  │ LAYER 1: AUDITS (structural — free, no LLM calls)      │  │   │
│  │  │  ├─ Documentation completeness                         │  │   │
│  │  │  ├─ Naming conventions                                 │  │   │
│  │  │  ├─ Metadata (VALUES, types)                           │  │   │
│  │  │  ├─ Relationships                                      │  │   │
│  │  │  └─ Inconsistencies / duplicates                       │  │   │
│  │  └─────────────────────────────────────────────────────────┘  │   │
│  │                              │                                 │   │
│  │                              ▼                                 │   │
│  │  ┌─────────────────────────────────────────────────────────┐  │   │
│  │  │ LAYER 2: QUESTION BANK EVALUATION (LLM-judged accuracy) │  │   │
│  │  │  ├─ Semantic View: easy / hard / ambiguous              │  │   │
│  │  │  └─ Agent (GPA): answerable / OOS / adversarial         │  │   │
│  │  └─────────────────────────────────────────────────────────┘  │   │
│  │                                                               │   │
│  │  Post results to PR comment → accuracy >= threshold?          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                    YES → merge → CD deploys to PROD                 │
│                    NO  → block merge, iterate                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

### Prerequisites

- Python 3.11+
- A Snowflake account with Cortex AI features enabled
- Existing semantic views and/or agents you want to govern
- A named connection in `~/.snowflake/connections.toml`
- [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code) (recommended)

### Bootstrap with Cortex Code (Recommended)

The framework ships a bundled Cortex Code skill at `.cortex/skills/bootstrap-from-existing/`. Cortex Code does not auto-discover skills bundled in a repo, so you register it once per clone, then invoke it.

1. Open this repo in Cortex Code.

2. Register the skill (one time per clone). Run this from the **repo root**:
   ```
   /skill add ./.cortex/skills/bootstrap-from-existing
   ```
   > `/skill add` resolves the relative path at add-time and stores an absolute path in `~/.snowflake/cortex/skills.json`. Run it from the repo root or the registration will point at the wrong location.

3. Invoke the skill:
   ```
   /bootstrap-from-existing
   ```

The skill will:
1. Discover your existing semantic views and agents (`SHOW SEMANTIC VIEWS/AGENTS IN ACCOUNT`)
2. Let you select which to bring under governance
3. Ask for a database + schema to store framework tables
4. Generate `config/environments.yaml`
5. Execute the setup SQL to create framework objects
6. Seed starter question banks from your semantic view structure

### Manual Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy config templates:
```bash
cp config/environments.yaml.template config/environments.yaml
cp config/thresholds.yaml.template config/thresholds.yaml
cp config/monitoring.yaml.template config/monitoring.yaml
```

3. Edit `config/environments.yaml` — fill in your semantic view FQNs, agent FQNs, and framework DB/schema.

4. Execute the setup SQL:
```bash
# Replace placeholders and run against your Snowflake account
# The bootstrap skill does this automatically — or run manually:
python -c "
sql = open('setup/00_framework_tables.sql').read()
sql = sql.replace('{{FRAMEWORK_DB}}', 'YOUR_DB')
sql = sql.replace('{{FRAMEWORK_SCHEMA}}', 'AGENTOPS')
sql = sql.replace('{{WAREHOUSE}}', 'YOUR_WH')
# Execute each statement...
"
```

5. Create question banks in `question_banks/` and run your first evaluation.

---

## Directory Structure

```
Snowflake_AgentOps_Framework/
├── .cortex/skills/                     # Cortex Code skills
│   └── bootstrap-from-existing/        # Interactive bootstrap from existing env
│       └── SKILL.md                    # Skill definition (register with /skill add)
├── app/                                # App Runtime monitoring dashboard (Next.js)
│   ├── app.yml                        # App Runtime manifest
│   ├── package.json
│   ├── app/                           # Next.js pages
│   │   ├── layout.tsx                 # Nav + layout
│   │   ├── page.tsx                   # Overview (KPIs + alerts)
│   │   ├── accuracy/page.tsx          # Eval accuracy trends
│   │   ├── quality/page.tsx           # Interaction quality flags
│   │   ├── cost/page.tsx              # Token cost trends
│   │   └── alerts/page.tsx            # Active alerts
│   └── lib/snowflake.ts              # Snowflake query helper
├── ci/                                 # CI/CD — vendor-neutral
│   ├── README.md                      # Pipeline stages & wiring guide
│   └── github/                        # GitHub Actions examples
├── config/                             # All configuration
│   ├── defaults.yaml                  # Universal: LLM models + credit pricing
│   ├── environments.yaml.template     # Instance config template
│   ├── monitoring.yaml.template       # Alert thresholds
│   └── thresholds.yaml.template       # Eval accuracy thresholds
├── docs/                               # Reference & explanation docs
│   ├── README.md                      # Documentation index
│   ├── explanation/                   # Design & intent
│   └── reference/                     # Lookup-style: cost model
├── evaluation/                         # All evaluation + monitoring Python
│   ├── audit_semantic_view.py         # Best practices audit (structural)
│   ├── audit_agent.py                 # Native GPA evaluation
│   ├── evaluate_semantic_view.py      # Batch SV eval (SQL + LLM judge)
│   ├── llm_judge.py                   # LLM-as-a-Judge
│   ├── discover_account.py            # Account discovery
│   ├── generate_question_bank.py      # Starter question-bank generator
│   ├── health_check.py               # Health checks
│   ├── cost_reconcile.py             # Reconcile estimated vs actual credits
│   ├── adversarial_library.yaml       # Curated adversarial patterns
│   └── utils.py                       # Config loader + Snowflake helpers
├── question_banks/                     # Your question banks
│   ├── agent/                         # Answerable, OOS, adversarial
│   └── semantic_view/                 # Easy, hard, ambiguous
├── setup/                              # Snowflake setup SQL
│   ├── 00_framework_tables.sql        # All framework objects (tables, views, alerts, tasks)
│   └── deploy.py                      # Deploy SV/agent to an env (CI helper)
├── .gitignore
├── AGENT.md                           # CoCo agent instructions
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── NOTICE
├── README.md
└── requirements.txt
```

---

## Run Evaluations Locally

```bash
# Discover agents and semantic views in your account
python evaluation/discover_account.py --format json

# SV best practices audit (free — no LLM calls)
python evaluation/audit_semantic_view.py --environment dev --live --semantic-view DB.SCHEMA.MY_SV

# SV question bank evaluation
python evaluation/evaluate_semantic_view.py --environment dev

# Agent native GPA evaluation
python evaluation/audit_agent.py --environment dev

# Generate a starter question bank from your semantic view
python evaluation/generate_question_bank.py --semantic-view-yaml path/to/sv.yaml

# Health checks
python evaluation/health_check.py --environment dev
```

---

## Monitoring & Observability

The framework creates tables, views, alerts, and tasks in your chosen schema (see `setup/00_framework_tables.sql`).

### Automated Schedules (Snowflake Tasks)

| Schedule | What |
|----------|------|
| Daily 02:00 UTC | Token usage & cost aggregation |
| Daily 02:15 UTC | Feedback sentiment analysis |
| Daily 02:30 UTC | Interaction quality scan |

### Alerts (Snowflake Alerts)

| Alert | Trigger |
|-------|---------|
| Negative Feedback Spike | >25% negative feedback |
| Accuracy Regression | >10% accuracy drop |
| Latency Degradation | P95 > 30s |
| Cost Anomaly | Daily > 2x 7-day average |
| Error Spike | Error rate > 10% |
| Health Failure | Any UNHEALTHY check |
| Interaction Quality | >20% flagged or CRITICAL |

### Monitoring Dashboard (App Runtime)

Deploy the Next.js dashboard to Snowflake:

```bash
cd app && snow app setup --app-name="agentops-monitoring" && snow app deploy
```

The dashboard shows: KPIs, accuracy trends, interaction quality flags, token costs, and active alerts — all filterable by agent.

---

## CI/CD Pipeline

See [ci/README.md](ci/README.md) for full documentation on pipeline stages and how to wire them into GitHub Actions, GitLab CI, Azure DevOps, or any other CI system.

**Pipeline stages:**
1. **Audit** — structural checks (free)
2. **Evaluate** — question bank accuracy (LLM-judged)
3. **Deploy** — promote to production

---

## Configuring Thresholds

Edit `config/thresholds.yaml` to adjust quality gates:

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

## Documentation

| Document | Type | What it covers |
|----------|------|----------------|
| [ci/README.md](ci/README.md) | Guide | CI/CD pipeline stages + env vars |
| [docs/README.md](docs/README.md) | Index | Documentation map |
| [Cost model](docs/reference/cost-model.md) | Reference | Evaluation cost in AI Credits |
| [Input governance](docs/explanation/pillar-1-input-governance.md) | Explanation | Semantic view audit design |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch → PR → merge workflow.

## License

Licensed under the [Apache License 2.0](LICENSE) (see also [NOTICE](NOTICE)).
