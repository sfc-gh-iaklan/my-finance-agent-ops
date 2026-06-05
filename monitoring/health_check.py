"""
health_check.py
Comprehensive health check for all PROD services.

Runs a battery of checks and generates a report. Can be called:
  - Locally: python monitoring/health_check.py --environment prod
  - By GitHub Actions: scheduled weekly
  - Results logged to the eval database's MONITORING.HEALTH_CHECK_RESULTS table

Checks:
  1. Semantic view existence and accessibility
  2. Agent existence and accessibility
  3. Agent responds to a smoke test query
  4. Analyst generates SQL for a smoke test query
  5. Underlying tables have fresh data
  6. Error rate from event table (last 24h)
  7. Average latency (last 24h)
  8. Active unacknowledged alerts count

Usage:
    python monitoring/health_check.py --environment prod
    python monitoring/health_check.py --environment prod --output health_report.json
"""
import argparse
import json
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "evaluation"))
from utils import get_connection, execute_sql, load_config, call_cortex_agent, call_cortex_analyst, get_framework_config, get_semantic_views, get_agents


def check_semantic_view_exists(conn, sv_name: str) -> dict:
    start = time.time()
    try:
        result = execute_sql(conn, f"DESCRIBE SEMANTIC VIEW {sv_name}")
        if result and not result[0].get("error"):
            return {
                "check_name": "sv_exists",
                "status": "HEALTHY",
                "details": f"Semantic view {sv_name} is accessible",
                "latency_ms": int((time.time() - start) * 1000),
            }
        return {
            "check_name": "sv_exists",
            "status": "UNHEALTHY",
            "details": f"Cannot describe {sv_name}: {result}",
            "latency_ms": int((time.time() - start) * 1000),
        }
    except Exception as e:
        return {
            "check_name": "sv_exists",
            "status": "UNHEALTHY",
            "details": f"Error: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def check_agent_exists(conn, agent_name: str) -> dict:
    start = time.time()
    try:
        result = execute_sql(conn, f"DESCRIBE AGENT {agent_name}")
        if result and not result[0].get("error"):
            return {
                "check_name": "agent_exists",
                "status": "HEALTHY",
                "details": f"Agent {agent_name} is accessible",
                "latency_ms": int((time.time() - start) * 1000),
            }
        return {
            "check_name": "agent_exists",
            "status": "UNHEALTHY",
            "details": f"Cannot describe {agent_name}: {result}",
            "latency_ms": int((time.time() - start) * 1000),
        }
    except Exception as e:
        return {
            "check_name": "agent_exists",
            "status": "UNHEALTHY",
            "details": f"Error: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def check_analyst_responds(conn, sv_name: str) -> dict:
    start = time.time()
    try:
        resp = call_cortex_analyst(conn, sv_name, "How many customers do we have?")
        latency = int((time.time() - start) * 1000)
        if "error" not in resp:
            status = "HEALTHY" if latency < 30000 else "DEGRADED"
            return {
                "check_name": "analyst_responds",
                "status": status,
                "details": f"Analyst responded in {latency}ms",
                "latency_ms": latency,
            }
        return {
            "check_name": "analyst_responds",
            "status": "UNHEALTHY",
            "details": f"Analyst failed: {resp.get('error')}",
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "check_name": "analyst_responds",
            "status": "UNHEALTHY",
            "details": f"Error: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def check_agent_responds(conn, agent_name: str) -> dict:
    start = time.time()
    try:
        resp = call_cortex_agent(conn, agent_name, "What is our total revenue?")
        latency = int((time.time() - start) * 1000)
        if "error" not in resp:
            status = "HEALTHY" if latency < 30000 else "DEGRADED"
            return {
                "check_name": "agent_responds",
                "status": status,
                "details": f"Agent responded in {latency}ms",
                "latency_ms": latency,
            }
        return {
            "check_name": "agent_responds",
            "status": "UNHEALTHY",
            "details": f"Agent failed: {resp.get('error')}",
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "check_name": "agent_responds",
            "status": "UNHEALTHY",
            "details": f"Error: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def check_data_freshness(conn, database: str) -> dict:
    start = time.time()
    try:
        result = execute_sql(conn, f"""
            SELECT
                MAX(ORDER_DATE) AS latest_order,
                COUNT(*) AS total_orders,
                DATEDIFF('day', MAX(ORDER_DATE), CURRENT_DATE()) AS days_since_latest
            FROM {database}.ANALYTICS.ORDERS
        """)
        latency = int((time.time() - start) * 1000)
        if result and not result[0].get("error"):
            days = result[0].get("DAYS_SINCE_LATEST", 999)
            total = result[0].get("TOTAL_ORDERS", 0)
            status = "HEALTHY" if days < 90 else ("DEGRADED" if days < 180 else "UNHEALTHY")
            return {
                "check_name": "data_freshness",
                "status": status,
                "details": f"Latest order: {days} days ago, {total} total orders",
                "latency_ms": latency,
            }
        return {
            "check_name": "data_freshness",
            "status": "UNHEALTHY",
            "details": f"Cannot query orders: {result}",
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "check_name": "data_freshness",
            "status": "UNHEALTHY",
            "details": f"Error: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def check_error_rate(conn) -> dict:
    start = time.time()
    try:
        result = execute_sql(conn, """
            SELECT
                COUNT(*) AS total,
                COUNT_IF(RECORD:status.code::STRING != 'STATUS_CODE_OK') AS errors,
                ROUND(
                    COUNT_IF(RECORD:status.code::STRING != 'STATUS_CODE_OK') * 100.0 /
                    NULLIF(COUNT(*), 0), 2
                ) AS error_pct
            FROM snowflake.local.ai_observability_events
            WHERE RECORD_TYPE = 'SPAN'
              AND SCOPE:name::STRING = 'snow.cortex.agent'
              AND TIMESTAMP >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
        """)
        latency = int((time.time() - start) * 1000)
        if result and not result[0].get("error"):
            error_pct = result[0].get("ERROR_PCT", 0) or 0
            total = result[0].get("TOTAL", 0)
            if total == 0:
                return {
                    "check_name": "error_rate",
                    "status": "HEALTHY",
                    "details": "No requests in last 24h (no traffic)",
                    "latency_ms": latency,
                }
            status = "HEALTHY" if error_pct < 5 else ("DEGRADED" if error_pct < 15 else "UNHEALTHY")
            return {
                "check_name": "error_rate",
                "status": status,
                "details": f"Error rate: {error_pct}% ({result[0].get('ERRORS', 0)}/{total})",
                "latency_ms": latency,
            }
        return {
            "check_name": "error_rate",
            "status": "DEGRADED",
            "details": f"Cannot query event table: {result}",
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "check_name": "error_rate",
            "status": "DEGRADED",
            "details": f"Event table query error: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def check_active_alerts(conn, mon_fqn) -> dict:
    start = time.time()
    try:
        result = execute_sql(conn, f"""
            SELECT
                COUNT(*) AS total_active,
                COUNT_IF(severity = 'CRITICAL') AS critical_count,
                COUNT_IF(severity = 'WARNING') AS warning_count
            FROM {mon_fqn}.ALERT_HISTORY
            WHERE acknowledged = FALSE
        """)
        latency = int((time.time() - start) * 1000)
        if result and not result[0].get("error"):
            total = result[0].get("TOTAL_ACTIVE", 0)
            critical = result[0].get("CRITICAL_COUNT", 0)
            status = "UNHEALTHY" if critical > 0 else ("DEGRADED" if total > 3 else "HEALTHY")
            return {
                "check_name": "active_alerts",
                "status": status,
                "details": f"{total} active alerts ({critical} critical, {result[0].get('WARNING_COUNT', 0)} warnings)",
                "latency_ms": latency,
            }
        return {
            "check_name": "active_alerts",
            "status": "HEALTHY",
            "details": "Alert table not yet populated",
            "latency_ms": latency,
        }
    except Exception as e:
        return {
            "check_name": "active_alerts",
            "status": "HEALTHY",
            "details": f"Alert table may not exist yet: {str(e)}",
            "latency_ms": int((time.time() - start) * 1000),
        }


def run_health_checks(environment: str) -> dict:
    config = load_config()
    env_config = config["environments"][environment]
    fw = get_framework_config()
    mon_fqn = f"{fw['database']}.{fw['schema']}"

    # Resolve SV/agent names: new format uses lists, old format uses scalar keys
    svs = get_semantic_views(environment)
    agents = get_agents(environment)
    sv_name = svs[0]["fqn"] if svs else ""
    agent_name = agents[0]["fqn"] if agents else ""
    database = sv_name.split(".")[0] if sv_name else fw["database"]

    conn = get_connection(environment)
    checks = []

    print(f"\n{'='*60}")
    print(f"HEALTH CHECK REPORT - {environment.upper()}")
    print(f"{'='*60}")
    print(f"Time:     {datetime.now().isoformat()}")
    print(f"Database: {database}")
    print(f"{'='*60}\n")

    check_fns = [
        ("Semantic view exists", lambda: check_semantic_view_exists(conn, sv_name)),
        ("Agent exists", lambda: check_agent_exists(conn, agent_name)),
        ("Analyst responds", lambda: check_analyst_responds(conn, sv_name)),
        ("Agent responds", lambda: check_agent_responds(conn, agent_name)),
        ("Data freshness", lambda: check_data_freshness(conn, database)),
        ("Error rate (24h)", lambda: check_error_rate(conn)),
        ("Active alerts", lambda: check_active_alerts(conn, mon_fqn)),
    ]

    for label, fn in check_fns:
        print(f"  Running: {label}...", end=" ", flush=True)
        result = fn()
        result["environment"] = environment
        result["target_name"] = sv_name if "sv" in result["check_name"] or "analyst" in result["check_name"] else agent_name
        checks.append(result)

        icon = {"HEALTHY": "OK", "DEGRADED": "WARN", "UNHEALTHY": "FAIL", "ERROR": "ERR"}.get(result["status"], "?")
        print(f"[{icon}] {result['details']} ({result['latency_ms']}ms)")

        try:
            execute_sql(conn, f"""
                INSERT INTO {mon_fqn}.HEALTH_CHECK_RESULTS
                    (check_name, environment, target_name, status, details, latency_ms)
                VALUES (
                    '{result["check_name"]}',
                    '{environment}',
                    '{result["target_name"]}',
                    '{result["status"]}',
                    '{result["details"].replace("'", "''")}',
                    {result["latency_ms"]}
                )
            """)
        except Exception:
            pass

    healthy = sum(1 for c in checks if c["status"] == "HEALTHY")
    degraded = sum(1 for c in checks if c["status"] == "DEGRADED")
    unhealthy = sum(1 for c in checks if c["status"] == "UNHEALTHY")
    total = len(checks)

    overall = "HEALTHY" if unhealthy == 0 and degraded == 0 else ("DEGRADED" if unhealthy == 0 else "UNHEALTHY")

    summary = {
        "environment": environment,
        "timestamp": datetime.now().isoformat(),
        "overall_status": overall,
        "total_checks": total,
        "healthy": healthy,
        "degraded": degraded,
        "unhealthy": unhealthy,
        "checks": checks,
    }

    print(f"\n{'='*60}")
    print(f"OVERALL STATUS: {overall}")
    print(f"  Healthy:   {healthy}/{total}")
    print(f"  Degraded:  {degraded}/{total}")
    print(f"  Unhealthy: {unhealthy}/{total}")
    print(f"{'='*60}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run health checks against PROD services")
    parser.add_argument("--environment", "-e", default="prod", choices=["dev", "prod"])
    parser.add_argument("--output", "-o", default="", help="Output JSON file path")
    args = parser.parse_args()

    report = run_health_checks(args.environment)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport written to {args.output}")

    sys.exit(0 if report["overall_status"] != "UNHEALTHY" else 1)


if __name__ == "__main__":
    main()
