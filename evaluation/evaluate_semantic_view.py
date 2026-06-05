"""
evaluate_semantic_view.py
Batch evaluation of a semantic view against question banks.

Usage:
    python evaluate_semantic_view.py --environment dev          # uses the active instance's SV
    python evaluate_semantic_view.py --environment dev --categories easy,hard
    python evaluate_semantic_view.py --environment dev --git-sha abc123 --git-branch feature/update-sv
"""
import argparse
import json
import sys
import os
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from utils import (
    get_connection, load_question_bank, load_thresholds, load_config,
    execute_sql, call_cortex_analyst, log_eval_run, format_results_table,
    get_semantic_views, get_framework_config,
)
from llm_judge import judge_sql_result, judge_ambiguous_result


def extract_sql_from_analyst_response(response: dict) -> str:
    """Extract the generated SQL from a Cortex Analyst response.

    The active call_cortex_analyst (REST /api/v2/cortex/analyst/message) returns
    {"content": [{"type": "text", ...}, {"type": "sql", "statement": "..."}]}.
    A legacy/agent shape {"choices": [{"messages": [{"type": "sql", ...}]}]} is
    also supported as a fallback. Returns "" when no SQL is present (e.g. an
    ambiguous question that yields only "suggestions", or an error response).
    """
    if not isinstance(response, dict):
        return ""
    # Primary: REST Cortex Analyst content blocks.
    for item in response.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "sql":
            return item.get("statement", "") or ""
    # Fallback: legacy choices/messages shape.
    try:
        choices = response.get("choices", [])
        if choices:
            messages = choices[0].get("messages", []) or choices[0].get("message", {}).get("content", [])
            if isinstance(messages, list):
                for msg in messages:
                    if isinstance(msg, dict) and msg.get("type") == "sql":
                        return msg.get("statement", "") or ""
            elif isinstance(messages, str):
                return messages
    except Exception:
        pass
    return ""


def _execution_error(rows) -> str:
    """If execute_sql returned a swallowed error sentinel, return its message; else ''."""
    if isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict) and "error" in rows[0]:
        return str(rows[0]["error"])
    return ""


def evaluate_question(conn, semantic_view: str, question: dict, env_database: str) -> dict:
    start_time = time.time()
    result = {
        "question_id": question["id"],
        "question_text": question["question"],
        "difficulty": question.get("category", "unknown"),
    }

    analyst_response = call_cortex_analyst(conn, semantic_view, question["question"])

    # Surface analyst-side errors explicitly rather than treating them as "no SQL".
    if isinstance(analyst_response, dict) and analyst_response.get("error"):
        result["generated_sql"] = ""
        result["latency_ms"] = int((time.time() - start_time) * 1000)
        result["match_status"] = "ANALYST_ERROR"
        result["llm_judge_score"] = 0.0
        result["llm_judge_reasoning"] = f"Cortex Analyst error: {analyst_response['error']}"
        return result

    generated_sql = extract_sql_from_analyst_response(analyst_response)
    result["generated_sql"] = generated_sql
    result["latency_ms"] = int((time.time() - start_time) * 1000)

    if not generated_sql:
        result["match_status"] = "NO_SQL_GENERATED"
        result["llm_judge_score"] = 0.0
        result["llm_judge_reasoning"] = "Cortex Analyst did not generate SQL (ambiguous question or no answer)"
        return result

    if question.get("category") == "ambiguous":
        generated_result = execute_sql(conn, generated_sql)
        result["generated_result"] = generated_result
        gen_err = _execution_error(generated_result)
        if gen_err:
            result["match_status"] = "EXECUTION_ERROR"
            result["llm_judge_score"] = 0.0
            result["llm_judge_reasoning"] = f"Generated SQL failed to execute: {gen_err}"
            return result
        judge_result = judge_ambiguous_result(
            conn,
            question["question"],
            question.get("evaluation_criteria", ""),
            generated_sql,
            generated_result,
        )
        result["match_status"] = "PASSED" if judge_result.get("passed") else "FAILED"
        result["llm_judge_score"] = judge_result.get("overall_score", 0)
        result["llm_judge_reasoning"] = judge_result.get("reasoning", "")
    else:
        expected_sql = question.get("expected_sql", "")
        expected_result = execute_sql(conn, expected_sql) if expected_sql else []
        generated_result = execute_sql(conn, generated_sql)
        result["expected_sql"] = expected_sql
        result["expected_result"] = expected_result
        result["generated_result"] = generated_result

        gen_err = _execution_error(generated_result)
        if gen_err:
            # The generated SQL could not run (e.g. permission denied, syntax) -- this is
            # an execution failure, not a "wrong answer". Surface it so it is diagnosable.
            result["match_status"] = "EXECUTION_ERROR"
            result["llm_judge_score"] = 0.0
            result["llm_judge_reasoning"] = f"Generated SQL failed to execute: {gen_err}"
            return result

        judge_result = judge_sql_result(
            conn, question["question"], expected_sql, generated_sql,
            expected_result, generated_result,
        )
        result["match_status"] = "PASSED" if judge_result.get("passed") else "FAILED"
        result["llm_judge_score"] = judge_result.get("overall_score", 0)
        result["llm_judge_reasoning"] = judge_result.get("reasoning", "")

    return result


def run_evaluation(
    environment: str,
    semantic_view: str,
    categories: list = None,
    git_sha: str = "",
    git_branch: str = "",
) -> dict:
    if categories is None:
        categories = ["easy", "hard", "ambiguous"]

    conn = get_connection(environment)
    thresholds = load_thresholds()
    env_thresholds = thresholds.get("semantic_view", {}).get(environment, thresholds["semantic_view"]["default"])
    env_database = get_framework_config()["database"]

    all_results = []
    for category in categories:
        questions = load_question_bank("semantic_view", category)
        print(f"\n{'='*60}")
        print(f"Evaluating {len(questions)} {category.upper()} questions")
        print(f"{'='*60}")

        for q in questions:
            print(f"  [{q['id']}] {q['question'][:60]}...", end=" ")
            result = evaluate_question(
                conn, semantic_view, q,
                env_database=env_database
            )
            status = result["match_status"]
            score = result.get("llm_judge_score", 0)
            print(f"{'PASS' if status == 'PASSED' else 'FAIL'} (score: {score:.2f}, {result['latency_ms']}ms)")
            all_results.append(result)

    passed = sum(1 for r in all_results if r["match_status"] == "PASSED")
    total = len(all_results)
    accuracy = (passed / total * 100) if total > 0 else 0
    threshold = env_thresholds.get("accuracy_threshold", 80)
    passed_threshold = accuracy >= threshold

    summary = {
        "environment": environment,
        "semantic_view_name": semantic_view,
        "git_commit_sha": git_sha,
        "git_branch": git_branch,
        "total_questions": total,
        "passed_questions": passed,
        "failed_questions": total - passed,
        "accuracy_pct": round(accuracy, 2),
        "threshold_pct": threshold,
        "passed_threshold": passed_threshold,
        "run_details": {
            "categories": categories,
            "by_category": {},
        },
    }

    for cat in categories:
        cat_results = [r for r in all_results if r["difficulty"] == cat]
        cat_passed = sum(1 for r in cat_results if r["match_status"] == "PASSED")
        cat_total = len(cat_results)
        summary["run_details"]["by_category"][cat] = {
            "total": cat_total,
            "passed": cat_passed,
            "accuracy_pct": round(cat_passed / cat_total * 100, 2) if cat_total > 0 else 0,
        }

    print(f"\n{'='*60}")
    print(f"EVALUATION SUMMARY")
    print(f"{'='*60}")
    print(f"Environment:    {environment}")
    print(f"Semantic View:  {semantic_view}")
    print(f"Total:          {total}")
    print(f"Passed:         {passed}")
    print(f"Failed:         {total - passed}")
    print(f"Accuracy:       {accuracy:.1f}%")
    print(f"Threshold:      {threshold}%")
    print(f"Result:         {'PASSED' if passed_threshold else 'FAILED'}")
    print(f"{'='*60}")

    for cat, stats in summary["run_details"]["by_category"].items():
        print(f"  {cat:12s}:  {stats['passed']}/{stats['total']} ({stats['accuracy_pct']:.1f}%)")

    try:
        log_eval_run(conn, "SEMANTIC_VIEW_EVAL_RUNS", summary)
        for r in all_results:
            log_eval_run(conn, "SEMANTIC_VIEW_EVAL_DETAILS", {
                "eval_run_id": summary.get("eval_run_id", ""),
                **{k: v for k, v in r.items() if k not in ("expected_result", "generated_result")},
                "expected_result": r.get("expected_result", []),
                "generated_result": r.get("generated_result", []),
            })
    except Exception as e:
        print(f"Warning: Could not log results to Snowflake: {e}")

    return {"summary": summary, "details": all_results, "passed_threshold": passed_threshold}


def main():
    parser = argparse.ArgumentParser(description="Evaluate a semantic view against question banks")
    parser.add_argument("--environment", "-e", default="dev", choices=["dev", "prod"])
    parser.add_argument("--semantic-view", "-s", default=None, help="Fully qualified semantic view name. Defaults to config[environments][env].semantic_view")
    parser.add_argument("--categories", "-c", default="easy,hard,ambiguous", help="Comma-separated categories")
    parser.add_argument("--git-sha", default="", help="Git commit SHA for tracking")
    parser.add_argument("--git-branch", default="", help="Git branch name for tracking")
    parser.add_argument("--output", "-o", default="", help="Output JSON file path")
    args = parser.parse_args()

    categories = [c.strip() for c in args.categories.split(",")]
    result = run_evaluation(
        environment=args.environment,
        semantic_view=args.semantic_view or get_semantic_views(args.environment)[0]["fqn"],
        categories=categories,
        git_sha=args.git_sha,
        git_branch=args.git_branch,
    )

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"\nResults written to {args.output}")

    sys.exit(0 if result["passed_threshold"] else 1)


if __name__ == "__main__":
    main()
