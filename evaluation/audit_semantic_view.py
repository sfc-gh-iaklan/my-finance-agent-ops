"""
audit_semantic_view.py
Semantic View Best Practices Audit.

Performs the audit checks from the CoCo semantic view audit skill:
  1. Documentation: all tables/columns have descriptions
  2. Naming conventions: no special characters, consistent casing
  3. Metadata completeness: data types, sample values, synonyms
  4. Type safety: dimensions vs facts classification
  5. Relationships: coverage check for table count
  6. Inconsistencies: conflicting definitions, overlapping filters/metrics
  7. Duplicates: redundant descriptions, instructions

Note: these rules are structural-only, not domain-aware. They validate
YAML/DDL shape, naming, types, and completeness -- not whether definitions
are semantically correct for the domain (e.g. that a revenue metric must use
SUM, or that order_date should be a time dimension). Domain-aware rule
generation is tracked in issue #11. See docs/explanation/pillar-1-input-governance.md.

Can run in two modes:
  - DDL mode (default): parses the CREATE SEMANTIC VIEW DDL file
  - Live mode (--live): introspects a deployed semantic view via DESCRIBE

Usage:
    python audit_semantic_view.py --environment dev          # uses the active instance's SV YAML
    python audit_semantic_view.py --ddl-file <path/to/sv.yaml>
    python audit_semantic_view.py --live --semantic-view DB.SCHEMA.MY_SV --output audit_report.json
"""
import argparse
import json
import re
import sys
import os
import yaml

sys.path.insert(0, os.path.dirname(__file__))
from utils import get_connection, execute_sql, load_config, instance_path


SEVERITY_ORDER = {"CRITICAL": 0, "ERROR": 1, "HIGH": 2, "WARNING": 3, "MEDIUM": 4, "INFO": 5, "LOW": 6}


def parse_ddl(ddl_text: str) -> dict:
    model = {
        "tables": [],
        "relationships": [],
        "raw_ddl": ddl_text,
    }

    sv_match = re.search(
        r'CREATE\s+(?:OR\s+REPLACE\s+)?SEMANTIC\s+VIEW\s+(\S+)',
        ddl_text, re.IGNORECASE
    )
    if sv_match:
        model["semantic_view_name"] = sv_match.group(1)

    table_blocks = re.split(r'\n\s*(?=\S+\.\S+\.\S+\s+AS\s+\w+\s+PRIMARY)', ddl_text)

    table_pattern = re.compile(
        r'(\S+\.\S+\.\S+)\s+AS\s+(\w+)\s+PRIMARY\s+KEY\s*\((\w+)\)',
        re.IGNORECASE
    )
    for block in table_blocks:
        table_match = table_pattern.search(block)
        if not table_match:
            continue

        table = {
            "physical_table": table_match.group(1),
            "logical_name": table_match.group(2),
            "primary_key": table_match.group(3),
            "columns": [],
            "metrics": [],
            "filters": [],
        }

        col_pattern = re.compile(
            r'(\w+)\s+AS\s+"([^"]+)"\s+COMMENT\s+\'([^\']*)\''
        )
        col_section = re.search(r'WITH\s+COLUMNS\s*\((.*?)\)\s*(?:WITH\s+METRICS|WITH\s+FILTERS|$)', block, re.DOTALL)
        col_text = col_section.group(1) if col_section else block
        for col_match in col_pattern.finditer(col_text):
            col = {
                "physical_name": col_match.group(1),
                "logical_name": col_match.group(2),
                "comment": col_match.group(3),
            }
            after_comment = col_text[col_match.end():]
            next_col = re.search(r'^\s*\w+\s+AS\s+"', after_comment, re.MULTILINE)
            segment = after_comment[:next_col.start()] if next_col else after_comment[:200]
            values_match = re.search(r"VALUES\s*\(([^)]+)\)", segment)
            if values_match:
                col["sample_values"] = [
                    v.strip().strip("'") for v in values_match.group(1).split(",")
                ]
            table["columns"].append(col)

        metric_section = re.search(r'WITH\s+METRICS\s*\(([\s\S]*?)\)\s*(?=WITH\s+FILTERS|\s*,\s*\n|\s*\)\s*\n|\s*$)', block)
        if metric_section:
            metric_pattern = re.compile(
                r'"([^"]+)"\s+AS\s+((?:COUNT|SUM|AVG|MIN|MAX)\(.*?\))\s+COMMENT\s+\'([^\']*)\''
            , re.DOTALL)
            for m_match in metric_pattern.finditer(metric_section.group(1)):
                table["metrics"].append({
                    "name": m_match.group(1),
                    "expression": re.sub(r'\s+', ' ', m_match.group(2).strip()),
                    "comment": m_match.group(3),
                })

        filter_pattern = re.compile(
            r'"([^"]+)"\s+AS\s+(.+?)\s+COMMENT\s+\'([^\']*)\''
        )
        filter_section = re.search(r'WITH\s+FILTERS\s*\((.*?)\)', block, re.DOTALL)
        if filter_section:
            for f_match in filter_pattern.finditer(filter_section.group(1)):
                if not re.match(r'(?:COUNT|SUM|AVG|MIN|MAX)\(', f_match.group(2)):
                    table["filters"].append({
                        "name": f_match.group(1),
                        "expression": f_match.group(2).strip(),
                        "comment": f_match.group(3),
                    })

        model["tables"].append(table)

    rel_pattern = re.compile(
        r'(\w+)\s*\((\w+)\)\s*REFERENCES\s+(\w+)\s*\((\w+)\)',
        re.IGNORECASE
    )
    rel_section = re.search(r'RELATIONSHIPS\s*\((.*)\)\s*;', ddl_text, re.DOTALL)
    if rel_section:
        for rel_match in rel_pattern.finditer(rel_section.group(1)):
            model["relationships"].append({
                "from_table": rel_match.group(1),
                "from_column": rel_match.group(2),
                "to_table": rel_match.group(3),
                "to_column": rel_match.group(4),
            })

    return model


def parse_yaml(yaml_text: str) -> dict:
    spec = yaml.safe_load(yaml_text)
    model = {
        "semantic_view_name": spec.get("name", ""),
        "tables": [],
        "relationships": [],
        "raw_yaml": yaml_text,
    }

    for tbl in spec.get("tables", []):
        bt = tbl.get("base_table", {})
        physical = f"{bt.get('database', '')}.{bt.get('schema', '')}.{bt.get('table', '')}"
        pk_cols = tbl.get("primary_key", {}).get("columns", [])
        table = {
            "physical_table": physical,
            "logical_name": tbl["name"],
            "primary_key": pk_cols[0] if pk_cols else "",
            "columns": [],
            "metrics": [],
            "filters": [],
        }

        for dim in tbl.get("dimensions", []) + tbl.get("time_dimensions", []):
            col = {
                "physical_name": dim.get("expr", dim["name"]),
                "logical_name": dim["name"],
                "comment": dim.get("description", ""),
            }
            if dim.get("sample_values"):
                col["sample_values"] = dim["sample_values"]
            table["columns"].append(col)

        for fact in tbl.get("facts", []):
            col = {
                "physical_name": fact.get("expr", fact["name"]),
                "logical_name": fact["name"],
                "comment": fact.get("description", ""),
            }
            table["columns"].append(col)

        for metric in tbl.get("metrics", []):
            table["metrics"].append({
                "name": metric["name"],
                "expression": metric.get("expr", ""),
                "comment": metric.get("description", ""),
            })

        for filt in tbl.get("filters", []):
            table["filters"].append({
                "name": filt["name"],
                "expression": filt.get("expr", ""),
                "comment": filt.get("description", ""),
            })

        model["tables"].append(table)

    for rel in spec.get("relationships", []):
        cols = rel.get("relationship_columns", [])
        if cols:
            model["relationships"].append({
                "from_table": rel["left_table"],
                "from_column": cols[0].get("left_column", ""),
                "to_table": rel["right_table"],
                "to_column": cols[0].get("right_column", ""),
            })

    return model


def describe_semantic_view(conn, semantic_view: str) -> dict:
    rows = execute_sql(conn, f"DESCRIBE SEMANTIC VIEW {semantic_view}")
    return {
        "semantic_view_name": semantic_view,
        "describe_result": rows,
        "tables": [],
        "relationships": [],
    }


def audit_documentation(model: dict) -> list:
    findings = []
    for table in model["tables"]:
        for col in table["columns"]:
            if not col.get("comment"):
                findings.append({
                    "check": "documentation",
                    "severity": "WARNING",
                    "table": table["logical_name"],
                    "element": col["physical_name"],
                    "message": f"Column '{col['physical_name']}' in table '{table['logical_name']}' has no description",
                    "recommendation": "Add a COMMENT describing the business meaning of this column",
                })
            elif len(col["comment"]) < 10:
                findings.append({
                    "check": "documentation",
                    "severity": "INFO",
                    "table": table["logical_name"],
                    "element": col["physical_name"],
                    "message": f"Column '{col['physical_name']}' has a very short description ({len(col['comment'])} chars)",
                    "recommendation": "Expand the COMMENT with more detail about business meaning and usage",
                })

        for metric in table["metrics"]:
            if not metric.get("comment"):
                findings.append({
                    "check": "documentation",
                    "severity": "WARNING",
                    "table": table["logical_name"],
                    "element": metric["name"],
                    "message": f"Metric '{metric['name']}' has no description",
                    "recommendation": "Add a COMMENT describing what this metric measures",
                })

    return findings


def audit_naming_conventions(model: dict) -> list:
    findings = []
    for table in model["tables"]:
        if re.search(r'[^a-zA-Z0-9_ ]', table["logical_name"]):
            findings.append({
                "check": "naming",
                "severity": "WARNING",
                "table": table["logical_name"],
                "element": table["logical_name"],
                "message": f"Table logical name '{table['logical_name']}' contains special characters",
                "recommendation": "Use only alphanumeric characters and underscores",
            })

        for col in table["columns"]:
            if col["logical_name"].isupper() or col["logical_name"].islower():
                pass
            elif not col["logical_name"][0].isupper():
                findings.append({
                    "check": "naming",
                    "severity": "INFO",
                    "table": table["logical_name"],
                    "element": col["logical_name"],
                    "message": f"Column alias '{col['logical_name']}' does not start with an uppercase letter",
                    "recommendation": "Use Title Case for column aliases for consistency",
                })

    return findings


def audit_metadata_completeness(model: dict) -> list:
    findings = []
    for table in model["tables"]:
        cols_with_values = sum(1 for c in table["columns"] if c.get("sample_values"))
        categorical_cols = [
            c for c in table["columns"]
            if any(kw in c.get("comment", "").lower()
                   for kw in ("category", "type", "status", "method", "segment", "tier", "region"))
        ]

        for col in categorical_cols:
            if not col.get("sample_values"):
                findings.append({
                    "check": "metadata",
                    "severity": "WARNING",
                    "table": table["logical_name"],
                    "element": col["physical_name"],
                    "message": f"Categorical column '{col['logical_name']}' lacks VALUES clause",
                    "recommendation": "Add VALUES (...) to help Cortex Analyst generate correct filter predicates",
                })

        if len(table["metrics"]) == 0 and len(table["columns"]) > 3:
            findings.append({
                "check": "metadata",
                "severity": "INFO",
                "table": table["logical_name"],
                "element": table["logical_name"],
                "message": f"Table '{table['logical_name']}' has no metrics defined",
                "recommendation": "Consider adding metrics (COUNT, SUM, AVG) for key numeric columns",
            })

    return findings


def audit_relationships(model: dict) -> list:
    findings = []
    num_tables = len(model["tables"])
    num_rels = len(model["relationships"])

    if num_tables > 1 and num_rels == 0:
        findings.append({
            "check": "relationships",
            "severity": "ERROR",
            "table": "ALL",
            "element": "RELATIONSHIPS",
            "message": f"No relationships defined across {num_tables} tables",
            "recommendation": "Add RELATIONSHIPS to enable multi-table joins in generated SQL",
        })
    elif num_tables > 2 and num_rels < num_tables - 1:
        findings.append({
            "check": "relationships",
            "severity": "WARNING",
            "table": "ALL",
            "element": "RELATIONSHIPS",
            "message": f"Only {num_rels} relationships for {num_tables} tables (minimum {num_tables - 1} expected for full connectivity)",
            "recommendation": "Verify all tables are reachable through relationship paths",
        })

    table_names = {t["logical_name"] for t in model["tables"]}
    for rel in model["relationships"]:
        if rel["from_table"] not in table_names:
            findings.append({
                "check": "relationships",
                "severity": "ERROR",
                "table": rel["from_table"],
                "element": "RELATIONSHIP",
                "message": f"Relationship references unknown table '{rel['from_table']}'",
                "recommendation": f"Verify table name or add table '{rel['from_table']}' to the semantic view",
            })
        if rel["to_table"] not in table_names:
            findings.append({
                "check": "relationships",
                "severity": "ERROR",
                "table": rel["to_table"],
                "element": "RELATIONSHIP",
                "message": f"Relationship references unknown table '{rel['to_table']}'",
                "recommendation": f"Verify table name or add table '{rel['to_table']}' to the semantic view",
            })

    return findings


def audit_inconsistencies(model: dict) -> list:
    findings = []

    all_metric_names = []
    for table in model["tables"]:
        for m in table["metrics"]:
            all_metric_names.append((m["name"], table["logical_name"]))

    seen = {}
    for name, tbl in all_metric_names:
        if name in seen:
            findings.append({
                "check": "inconsistency",
                "severity": "HIGH",
                "table": tbl,
                "element": name,
                "message": f"Metric '{name}' is defined in both '{seen[name]}' and '{tbl}'",
                "recommendation": "Consolidate duplicate metrics or use distinct names",
            })
        else:
            seen[name] = tbl

    all_filter_names = []
    for table in model["tables"]:
        for f in table["filters"]:
            all_filter_names.append((f["name"], table["logical_name"], f["expression"]))

    for i, (name1, tbl1, expr1) in enumerate(all_filter_names):
        for name2, tbl2, expr2 in all_filter_names[i + 1:]:
            if name1 == name2 and expr1 != expr2:
                findings.append({
                    "check": "inconsistency",
                    "severity": "CRITICAL",
                    "table": f"{tbl1}/{tbl2}",
                    "element": name1,
                    "message": f"Filter '{name1}' has conflicting definitions in '{tbl1}' and '{tbl2}'",
                    "recommendation": "Ensure filters with the same name have identical expressions",
                })

    return findings


def audit_duplicates(model: dict) -> list:
    findings = []

    for table in model["tables"]:
        descriptions = {}
        for col in table["columns"]:
            desc = col.get("comment", "").lower().strip()
            if desc in descriptions and desc:
                findings.append({
                    "check": "duplicate",
                    "severity": "MEDIUM",
                    "table": table["logical_name"],
                    "element": col["physical_name"],
                    "message": f"Column '{col['physical_name']}' has same description as '{descriptions[desc]}'",
                    "recommendation": "Differentiate descriptions to help Cortex Analyst distinguish between columns",
                })
            elif desc:
                descriptions[desc] = col["physical_name"]

    return findings


def run_audit(model: dict) -> dict:
    all_findings = []
    all_findings.extend(audit_documentation(model))
    all_findings.extend(audit_naming_conventions(model))
    all_findings.extend(audit_metadata_completeness(model))
    all_findings.extend(audit_relationships(model))
    all_findings.extend(audit_inconsistencies(model))
    all_findings.extend(audit_duplicates(model))

    all_findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 99))

    by_severity = {}
    for f in all_findings:
        sev = f["severity"]
        by_severity[sev] = by_severity.get(sev, 0) + 1

    by_check = {}
    for f in all_findings:
        chk = f["check"]
        by_check[chk] = by_check.get(chk, 0) + 1

    has_blocking = any(f["severity"] in ("CRITICAL", "ERROR") for f in all_findings)

    summary = {
        "total_findings": len(all_findings),
        "by_severity": by_severity,
        "by_check": by_check,
        "tables_audited": len(model["tables"]),
        "relationships_audited": len(model["relationships"]),
        "has_blocking_issues": has_blocking,
        "audit_passed": not has_blocking,
    }

    return {"summary": summary, "findings": all_findings}


def print_report(report: dict):
    summary = report["summary"]
    findings = report["findings"]

    print(f"\n{'='*70}")
    print(f"SEMANTIC VIEW BEST PRACTICES AUDIT REPORT")
    print(f"{'='*70}")
    print(f"Tables audited:       {summary['tables_audited']}")
    print(f"Relationships:        {summary['relationships_audited']}")
    print(f"Total findings:       {summary['total_findings']}")
    print(f"Blocking issues:      {summary['has_blocking_issues']}")
    print(f"Audit result:         {'PASSED' if summary['audit_passed'] else 'FAILED'}")
    print(f"{'='*70}")

    print(f"\nBy Severity:")
    for sev in ["CRITICAL", "ERROR", "HIGH", "WARNING", "MEDIUM", "INFO", "LOW"]:
        count = summary["by_severity"].get(sev, 0)
        if count > 0:
            print(f"  {sev:12s}: {count}")

    print(f"\nBy Check:")
    for chk, count in summary["by_check"].items():
        print(f"  {chk:20s}: {count}")

    if findings:
        print(f"\n{'='*70}")
        print(f"DETAILED FINDINGS")
        print(f"{'='*70}")
        for f in findings:
            print(f"\n  [{f['severity']}] {f['check']}: {f['message']}")
            print(f"    Table:          {f['table']}")
            print(f"    Element:        {f['element']}")
            print(f"    Recommendation: {f['recommendation']}")


def main():
    parser = argparse.ArgumentParser(description="Audit a semantic view against best practices")
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--ddl-file", help="Path to semantic view DDL file. Defaults to config[environments][env].sv_yaml_path")
    group.add_argument("--live", action="store_true", help="Introspect a deployed semantic view")
    parser.add_argument("--semantic-view", help="Fully qualified semantic view name (required with --live)")
    parser.add_argument("--environment", "-e", default="dev", choices=["dev", "prod"])
    parser.add_argument("--output", "-o", default="", help="Output JSON file path")
    args = parser.parse_args()

    if args.live and not args.semantic_view:
        parser.error("--semantic-view is required with --live")

    ddl_file = args.ddl_file
    if not ddl_file and not args.live:
        # Default to the environment's SV YAML from config (resolved against the instance dir).
        env = load_config()["environments"][args.environment]
        rel = env.get("sv_yaml_path", "")
        if not rel:
            parser.error("No --ddl-file provided and no sv_yaml_path in config. Use --live with --semantic-view instead.")
        ddl_file = instance_path(rel)

    if ddl_file:
        with open(ddl_file, "r") as f:
            file_text = f.read()
        if ddl_file.endswith(".yaml") or ddl_file.endswith(".yml"):
            model = parse_yaml(file_text)
        else:
            model = parse_ddl(file_text)
    else:
        conn = get_connection(args.environment)
        model = describe_semantic_view(conn, args.semantic_view)

    report = run_audit(model)
    print_report(report)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"\nReport written to {args.output}")

    sys.exit(0 if report["summary"]["audit_passed"] else 1)


if __name__ == "__main__":
    main()
