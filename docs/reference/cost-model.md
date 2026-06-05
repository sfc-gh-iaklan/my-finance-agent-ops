# Cost model

> Status: Stable | Last reviewed: 2026-06-04 | Audience: Engineers, solution architects, customers

**Purpose.** Explain how the framework's evaluation cost is computed, in Snowflake AI Credits, so teams can estimate and budget spend before adopting it.

## Canonical unit: Snowflake AI Credits

All cost in this framework is denominated in **Snowflake AI Credits**, not US dollars. The monitoring schema stores cost in the `estimated_credits` column ([setup/00_framework_tables.sql](../../setup/00_framework_tables.sql)), computed from real per-model token counts using the rate table in the `pricing:` block of [config/defaults.yaml](../../config/defaults.yaml).

Dollar cost depends on your Snowflake contract's credit price, which varies by edition, region, and commitment. This document therefore quotes credits only.

> Note: some demo materials loosely quote figures like "$5 per run" and "$1 per credit". Those are illustrative only and are not the canonical model. They are flagged for correction in the demo docs.

## Two loops, two cost profiles

The framework has two evaluation loops with very different cost characteristics:

| Loop | What it is | Cost driver | Approximate cost |
| --- | --- | --- | --- |
| Loop 1 (CI eval) | Agent run against a question bank, scored by an LLM judge | LLM tokens (agent + judge) | The subject of this document |
| Loop 2 (runtime monitoring) | Deterministic SQL rules over `ai_observability_events` | Warehouse compute only | No LLM tokens; cost is limited to short daily task runs on the configured warehouse |

Loop 2 is pure SQL aggregation on an XSMALL warehouse running short daily tasks. Its cost is negligible and not modeled here. The rest of this document is about Loop 1.

## How Loop 1 cost is computed

For each evaluation run, the framework:

1. Invokes the agent once per question in the bank (the agent plans, calls tools, generates SQL, and synthesizes an answer).
2. Invokes an LLM judge once per metric per question to score the answer.

So a single question with `M` metrics costs: one agent invocation plus `M` judge invocations.

### Token assumptions (measured)

These figures are **calibrated against real eval runs**, not guessed. The agent values are measured medians from `OBSERVABILITY.AGENT_TRACES` (the `sample` in [config/defaults.yaml](../../config/defaults.yaml) `token_assumptions:`); the judge values remain estimates because judge tokens are not exposed in observability. Always prefer measured actuals (see "Measuring actuals") over any planning figure.

| Component | Input tokens | Cache-read input | Output tokens | Source |
| --- | --- | --- | --- | --- |
| Agent invocation (per question) | ~195,000 | ~116,000 (~85%) | ~410 | measured median |
| Judge invocation (per metric per question) | ~1,200 | n/a | ~300 | estimate (unmeasured) |

**Cache reads dominate the agent input.** A multi-step agent re-reads a large, mostly-cached context on every step, so ~85% of its input tokens are served from the prompt cache and billed at the much cheaper `cache_read_credits_per_million` rate -- not the full input rate. The credit formula ([evaluation/utils.py](../../evaluation/utils.py) `build_credits_expr`) charges `(input - cache_read)` at the input rate, `cache_read` at the cache rate, and `output` at the output rate. Ignoring the cache split (as earlier versions did) over-states agent cost ~5x.

### Per-model rates

Credits are computed from the model's input, cache-read, and output rates (credits per million tokens) in [config/defaults.yaml](../../config/defaults.yaml) (carries a `last_verified` date -- **estimates only; confirm against your Snowflake Service Consumption Table**, as rates drift). The default evaluation and judge model is `claude-opus-4-7`:

| Rate | Credits per million tokens |
| --- | --- |
| Input | 3.25 |
| Cache-read input | 0.33 |
| Output | 16.26 |

### Per-question credit estimate

Using the measured agent profile above with `claude-opus-4-7` and the default eight metrics (`answer_correctness`, `logical_consistency`, `safety`, `groundedness`, `execution_efficiency`, `answer_relevance`, `conciseness`, `pii_leakage`):

- Agent (cache-aware, measured): **~0.22 credits** per question (mean; median ~0.11 -- the distribution is right-skewed by occasional long multi-step questions). Use the mean for budgeting totals.
- Judges (8, estimated): `8 x (1200/1e6 x 3.25 + 300/1e6 x 16.26)` = approximately `0.070` credits
- **Per question: approximately `0.29` credits**

> Metric count is a direct cost lever: each judge metric is one extra `AI_COMPLETE` call per question, so judge cost scales linearly with the metric set. The set is configurable per environment in `thresholds.yaml` (`agent.<env>.metrics`) -- drop metrics you do not need to cut judge cost by `1/M` each. Cost/latency/step-count are derived deterministically from the eval results table (no judge call), so they add no judge cost.

> This is ~2.7x higher than the previous guessed figure (`0.096`), which assumed only ~6,000 agent input tokens. Calibration moved the estimate up on the agent side (far more tokens than assumed) even though cache-aware billing moved the *per-token* cost down. Your agent's token counts depend on your semantic model size, tools, and step count -- measure your own.

## Lifecycle cost formula

An evaluation runs on every CI trigger that touches a watched path (`examples/retail/agents/`, `examples/retail/semantic_views/`, `examples/retail/question_banks/`). Across a feature's life:

```text
E = number of promotion environments (e.g. DEV + STAGING + PROD = 3)

total_eval_runs = feature_branch_commits_touching_watched_paths
                + E   (one eval per promotion gate)

cost_credits = total_eval_runs
             x num_agents_changed
             x bank_size
             x per_question_credits
```

`per_question_credits` is approximately `0.29` for the default model and eight metrics (see above). `num_agents_changed` is usually 1 (a PR typically changes one agent); multi-agent PRs multiply accordingly. `E` depends on how many environments your pipeline promotes through — a minimal setup has 2 (DEV + PROD), while enterprise setups may have 3 or more (DEV + STAGING + PROD).

## Worked examples

All figures are estimates in AI Credits, assuming `claude-opus-4-7`, eight metrics, `per_question_credits` approximately `0.29` (cache-aware; agent measured + judge estimate), one agent changed per PR, and `E = 2` environments (DEV + PROD). Scale `E` for your pipeline. These are derived from the bundled retail example's measured agent profile; your own token counts will differ.

### Small team

- 1 agent, 20-question bank, ~3 commits per PR, 5 PRs per week
- Per run: `20 x 0.29` = approximately `5.8` credits
- Per PR: `(3 + E) runs x 5.8` = `(3 + 2) x 5.8` = approximately `29` credits
- **Per week: `5 x 29` = approximately 145 credits**

### Medium team

- 5 agents (1 changed per PR), 35-question bank, ~4 commits per PR, 50 PRs per week
- Per run: `35 x 0.29` = approximately `10.2` credits
- Per PR: `(4 + E) runs x 10.2` = `(4 + 2) x 10.2` = approximately `61` credits
- **Per week: `50 x 61` = approximately 3,050 credits**

### Large team

- 20 agents (1 changed per PR), 50-question bank, ~5 commits per PR, 200 PRs per week
- Per run: `50 x 0.29` = approximately `14.5` credits
- Per PR: `(5 + E) runs x 14.5` = `(5 + 2) x 14.5` = approximately `102` credits
- **Per week: `200 x 102` = approximately 20,400 credits**

## Levers to reduce cost

- **Pre-flight smoke check.** Run a 3-question smoke set before the full bank. A broken agent aborts at roughly `0.3` credits instead of running the full bank. This is the single biggest saver on iterative feature branches.
- **Tiered question banks.** Run a small subset on feature-branch commits (advisory) and the full bank only on merge to main. Cuts feature-branch cost by the ratio of the subsets.
- **Metric pruning.** Each judge metric is a judge call per question. The metric set is configurable per environment (`thresholds.yaml` `agent.<env>.metrics`); dropping a metric you do not need (for example `groundedness`) removes one judge call per question, reducing judge cost by roughly `1/M`. Cost, latency, and step-count are derived from the eval results table deterministically, so prefer those over a judge metric when the signal is numeric.
- **Cheaper judge model.** The judge model is configurable. A less expensive model (for example a Haiku-class model) lowers judge cost substantially, at some loss of judging nuance.

## Architecture note: why per-record, not batched

The framework scores each (question, metric) pair as its own judge call. A batched alternative — one judge call scoring all answers for a metric — would cut judge tokens by roughly 30 percent. It was rejected because it loses per-question explainability (the `EVAL_CALLS` rationale per record), breaks the Snowsight Evaluations UI integration, and abandons the native `EXECUTE_AI_EVALUATION` API. The modest savings did not justify those losses.

## Measuring actuals

Estimates are for planning. To see real cost, query the monitoring schema, which aggregates `estimated_credits` from measured token counts:

```sql
SELECT metric_date, service_type, agent_or_sv_name, total_tokens, estimated_credits
FROM RETAIL_AI_EVAL.MONITORING.USAGE_METRICS
ORDER BY metric_date DESC;
```

The dashboard's Token Costs tab visualizes the same data over time.

## Reconciling estimates against actuals

Estimates (token assumptions + per-token rates) drift. To catch this, [monitoring/cost_reconcile.py](../../monitoring/cost_reconcile.py) compares the framework's modeled `estimated_credits` (from `USAGE_METRICS`) against ground-truth account AI spend (`SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY`, `service_type = 'AI_SERVICES'`) over a window and flags when the estimate materially exceeds actuals (over-charging):

```bash
python monitoring/cost_reconcile.py --environment dev --days 30
```

The actual figure is broader than the estimate (it also includes judge calls and any other Cortex usage), so a healthy state is `estimated <= actual`. Reading the metering view requires `IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE`, so run this as an admin role (it is not part of the deployer CI path).
