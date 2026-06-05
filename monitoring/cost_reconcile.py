#!/usr/bin/env python3
"""
cost_reconcile.py
Reconcile the framework's ESTIMATED evaluation credits against ACTUAL Snowflake
AI-services credits, so stale token assumptions or per-token rates are caught
rather than silently misleading.

Two sources (see docs/reference/cost-model.md, "Two-tier cost model"):
  - Estimated: SUM(estimated_credits) from <eval_db>.MONITORING.USAGE_METRICS
    (modeled agent/analyst cost, cache-aware).
  - Actual:    SUM(credits_used) from SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
    where service_type = 'AI_SERVICES' (ground-truth account AI spend).

Scope note: the actual figure is broader than the estimate -- it includes judge
(COMPLETE) calls and any other Cortex AI usage in the account, which the estimate
does not model. So expect estimated <= actual in a healthy state. The check flags
the dangerous direction (estimated materially EXCEEDS actual => the model is
over-charging, as the pre-cache-aware formula did) and reports the ratio either way.

Requires ACCOUNT_USAGE access: GRANT IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE TO
ROLE <role>. The CI deployer role does not have this; run as an admin role (this
is an admin/manual or admin-scheduled check, not part of the deployer CI path).

Usage:
    python monitoring/cost_reconcile.py --environment dev --days 30
    python monitoring/cost_reconcile.py --days 7 --tolerance 2.0 --output recon.json
"""
import argparse
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evaluation"))
from utils import get_connection, execute_sql, load_config, get_framework_config  # noqa: E402


def _scalar(rows, key, default=0.0):
    if rows and isinstance(rows[0], dict) and not rows[0].get("error"):
        val = rows[0].get(key)
        return float(val) if val is not None else default
    return None  # signals query error / no access


def reconcile(conn, eval_db: str, monitoring_schema: str, days: int) -> dict:
    est_rows = execute_sql(conn, f"""
        SELECT COALESCE(SUM(estimated_credits), 0) AS est
        FROM {eval_db}.{monitoring_schema}.USAGE_METRICS
        WHERE metric_date >= DATEADD('day', -{days}, CURRENT_DATE())
    """)
    estimated = _scalar(est_rows, "EST")

    act_rows = execute_sql(conn, f"""
        SELECT COALESCE(SUM(credits_used), 0) AS act
        FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
        WHERE usage_date >= DATEADD('day', -{days}, CURRENT_DATE())
          AND service_type = 'AI_SERVICES'
    """)
    actual = _scalar(act_rows, "ACT")

    result = {"window_days": days, "estimated_credits": estimated, "actual_ai_credits": actual}
    if actual is None:
        result["status"] = "METERING_UNAVAILABLE"
        result["detail"] = ("Could not read SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY "
                            "(needs IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE; run as an admin role).")
        if act_rows and act_rows[0].get("error"):
            result["error"] = act_rows[0]["error"]
    elif estimated is None:
        result["status"] = "ESTIMATE_UNAVAILABLE"
    else:
        result["est_over_actual_ratio"] = round(estimated / actual, 3) if actual else None
    return result


def main():
    parser = argparse.ArgumentParser(description="Reconcile estimated vs actual AI credits.")
    parser.add_argument("--environment", "-e", default="dev", choices=["dev", "prod"])
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--tolerance", type=float, default=2.0,
                        help="Flag when estimated exceeds actual by more than this ratio (over-charging).")
    parser.add_argument("--output", "-o", default="")
    parser.add_argument("--strict", action="store_true", help="Exit 1 when drift exceeds tolerance.")
    args = parser.parse_args()

    cfg = load_config()
    fw = get_framework_config()
    conn = get_connection(args.environment)
    try:
        r = reconcile(conn, fw["database"], fw["schema"], args.days)
    finally:
        conn.close()

    print(f"\n{'='*60}\n  COST RECONCILIATION (last {args.days} days)\n{'='*60}")
    print(f"  Estimated eval credits (USAGE_METRICS):  {r.get('estimated_credits')}")
    print(f"  Actual AI_SERVICES credits (metering):   {r.get('actual_ai_credits')}")
    ratio = r.get("est_over_actual_ratio")
    flagged = False
    if r.get("status") in ("METERING_UNAVAILABLE", "ESTIMATE_UNAVAILABLE"):
        print(f"  Status: {r['status']} -- {r.get('detail', '')}")
    elif ratio is not None:
        print(f"  Estimated / Actual ratio:                {ratio}")
        if ratio > args.tolerance:
            flagged = True
            print(f"  FLAG: estimated exceeds actual by >{args.tolerance}x -- the cost model is over-charging "
                  f"(check token assumptions / cache-read handling / rates).")
        else:
            print("  OK: estimated is within tolerance of actual (estimate models a subset of AI spend, "
                  "so estimated <= actual is expected).")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(r, f, indent=2, default=str)
        print(f"\n  Written to {args.output}")

    sys.exit(1 if (flagged and args.strict) else 0)


if __name__ == "__main__":
    main()
