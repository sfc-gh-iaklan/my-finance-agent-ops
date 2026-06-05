-- ============================================================================
-- 00_framework_tables.sql
-- Minimal bootstrap: creates ONLY the framework's own tables and views
-- in a single user-provided database + schema.
--
-- This script is used by the "bootstrap-from-existing" workflow when the
-- customer already has their own databases, semantic views, and agents.
-- No RBAC, no warehouse creation, no data tables.
--
-- Placeholders:
--   {{FRAMEWORK_DB}}     — existing database to house framework objects
--   {{FRAMEWORK_SCHEMA}} — schema name (created if not exists)
-- ============================================================================

-- Create schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}};

-- ============================================================================
-- EVALUATION RESULTS
-- ============================================================================

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.SEMANTIC_VIEW_EVAL_RUNS (
    eval_run_id         STRING DEFAULT UUID_STRING(),
    environment         STRING,
    semantic_view_name  STRING,
    git_commit_sha      STRING,
    git_branch          STRING,
    total_questions     INTEGER,
    passed_questions    INTEGER,
    failed_questions    INTEGER,
    accuracy_pct        FLOAT,
    threshold_pct       FLOAT,
    passed_threshold    BOOLEAN,
    run_timestamp       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    run_details         VARIANT
);

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.SEMANTIC_VIEW_EVAL_DETAILS (
    eval_run_id         STRING,
    question_id         STRING,
    question_text       STRING,
    difficulty          STRING,
    expected_sql        STRING,
    generated_sql       STRING,
    expected_result     VARIANT,
    generated_result    VARIANT,
    match_status        STRING,
    llm_judge_score     FLOAT,
    llm_judge_reasoning STRING,
    latency_ms          INTEGER,
    eval_timestamp      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ============================================================================
-- MONITORING TABLES
-- ============================================================================

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USER_FEEDBACK (
    feedback_id         STRING DEFAULT UUID_STRING(),
    environment         STRING,
    source              STRING,
    agent_or_sv_name    STRING,
    user_query          STRING,
    agent_response      STRING,
    feedback_rating     INTEGER,
    feedback_text       STRING,
    feedback_category   STRING,
    sentiment_score     FLOAT,
    user_name           STRING DEFAULT CURRENT_USER(),
    created_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.SCHEDULED_EVAL_RUNS (
    run_id              STRING DEFAULT UUID_STRING(),
    run_type            STRING,
    environment         STRING,
    target_name         STRING,
    accuracy_pct        FLOAT,
    threshold_pct       FLOAT,
    passed_threshold    BOOLEAN,
    total_questions     INTEGER,
    passed_questions    INTEGER,
    failed_questions    INTEGER,
    accuracy_delta      FLOAT,
    run_details         VARIANT,
    run_timestamp       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS (
    metric_id           STRING DEFAULT UUID_STRING(),
    metric_date         DATE,
    environment         STRING,
    service_type        STRING,
    agent_or_sv_name    STRING,
    total_requests      INTEGER,
    successful_requests INTEGER,
    failed_requests     INTEGER,
    total_input_tokens  BIGINT,
    total_output_tokens BIGINT,
    total_tokens        BIGINT,
    total_cache_read_tokens BIGINT,
    estimated_credits   FLOAT,
    avg_latency_ms      FLOAT,
    p50_latency_ms      FLOAT,
    p95_latency_ms      FLOAT,
    p99_latency_ms      FLOAT,
    unique_users        INTEGER,
    collected_at        TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.HEALTH_CHECK_RESULTS (
    check_id            STRING DEFAULT UUID_STRING(),
    check_name          STRING,
    environment         STRING,
    target_name         STRING,
    status              STRING,
    details             STRING,
    latency_ms          INTEGER,
    checked_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY (
    alert_id            STRING DEFAULT UUID_STRING(),
    alert_type          STRING,
    severity            STRING,
    environment         STRING,
    target_name         STRING,
    message             STRING,
    metric_value        FLOAT,
    threshold_value     FLOAT,
    acknowledged        BOOLEAN DEFAULT FALSE,
    acknowledged_by     STRING,
    acknowledged_at     TIMESTAMP_NTZ,
    created_at          TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.FEEDBACK_DAILY_SUMMARY (
    summary_date        DATE,
    environment         STRING,
    agent_or_sv_name    STRING,
    total_feedback      INTEGER,
    positive_count      INTEGER,
    neutral_count       INTEGER,
    negative_count      INTEGER,
    avg_rating          FLOAT,
    avg_sentiment_score FLOAT,
    negative_pct        FLOAT,
    feedback_categories VARIANT,
    computed_at         TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- ============================================================================
-- OBSERVABILITY VIEWS (over snowflake.local.ai_observability_events)
-- ============================================================================

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.AGENT_TRACES AS
SELECT
    e.TIMESTAMP                                                              AS event_time,
    e.START_TIMESTAMP                                                        AS start_time,
    DATEDIFF('millisecond', e.START_TIMESTAMP, e.TIMESTAMP)                  AS duration_ms,
    e.TRACE:trace_id::STRING                                                 AS trace_id,
    e.TRACE:span_id::STRING                                                  AS span_id,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.database.name"::STRING        AS database_name,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.schema.name"::STRING          AS schema_name,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.object.name"::STRING          AS agent_name,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.object.type"::STRING          AS object_type,
    e.SCOPE:name::STRING                                                     AS scope_name,
    e.RECORD:name::STRING                                                    AS span_name,
    e.RECORD:status.code::STRING                                             AS status_code,
    e.RECORD:status.message::STRING                                          AS status_message,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.model"::STRING AS model_used,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.query"::STRING AS user_query,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.status"::STRING AS planning_status,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.duration"::FLOAT AS planning_duration_ms,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.input"::INTEGER     AS input_tokens,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.output"::INTEGER    AS output_tokens,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.total"::INTEGER     AS total_tokens,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.cache_read_input"::INTEGER AS cache_read_tokens,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.cache_write_input"::INTEGER AS cache_write_tokens,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.tool_selection.name"::STRING    AS tool_selected,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.tool_selection.id"::STRING      AS tool_selection_id,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.step_number"::INTEGER           AS step_number,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.thread_id"::STRING                       AS thread_id,
    e.RECORD_ATTRIBUTES:"request_id"::STRING                                                  AS request_id,
    e.RECORD_ATTRIBUTES:"ai.observability.input_id"::STRING                                   AS input_id
FROM snowflake.local.ai_observability_events e
WHERE e.RECORD_TYPE = 'SPAN'
  AND e.SCOPE:name::STRING = 'snow.cortex.agent';

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.AGENT_REQUEST_SUMMARY AS
SELECT
    trace_id,
    MIN(start_time)                                     AS request_start,
    MAX(event_time)                                     AS request_end,
    DATEDIFF('millisecond', MIN(start_time), MAX(event_time)) AS total_duration_ms,
    MAX(database_name)                                  AS database_name,
    MAX(schema_name)                                    AS schema_name,
    MAX(agent_name)                                     AS agent_name,
    MAX(model_used)                                     AS model_used,
    MAX(user_query)                                     AS user_query,
    MAX(status_code)                                    AS status_code,
    MAX(thread_id)                                      AS thread_id,
    SUM(COALESCE(input_tokens, 0))                      AS total_input_tokens,
    SUM(COALESCE(output_tokens, 0))                     AS total_output_tokens,
    SUM(COALESCE(total_tokens, 0))                      AS total_tokens,
    SUM(COALESCE(cache_read_tokens, 0))                 AS total_cache_read_tokens,
    MAX(step_number)                                    AS max_step_number,
    COUNT(DISTINCT tool_selected)                       AS distinct_tools_used,
    ARRAY_AGG(tool_selected) WITHIN GROUP (ORDER BY step_number) AS tools_used
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.AGENT_TRACES
WHERE span_name LIKE 'ReasoningAgentStepPlanning%'
   OR span_name LIKE 'CodingAgent.Step%'
GROUP BY trace_id;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ANALYST_QUERIES AS
SELECT
    e.TIMESTAMP                                                              AS query_time,
    e.START_TIMESTAMP                                                        AS start_time,
    DATEDIFF('millisecond', e.START_TIMESTAMP, e.TIMESTAMP)                  AS latency_ms,
    e.TRACE:trace_id::STRING                                                 AS trace_id,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.database.name"::STRING        AS database_name,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.schema.name"::STRING          AS schema_name,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.object.name"::STRING          AS agent_name,
    e.RECORD:name::STRING                                                    AS span_name,
    e.RECORD:status.code::STRING                                             AS status_code,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.query"::STRING AS natural_language_query,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.total"::INTEGER AS total_tokens,
    e.RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.tool_selection.name"::STRING AS tool_name
FROM snowflake.local.ai_observability_events e
WHERE e.RECORD_TYPE = 'SPAN'
  AND e.SCOPE:name::STRING = 'snow.cortex.agent'
  AND (e.RECORD:name::STRING ILIKE '%Analyst%' OR e.RECORD:name::STRING ILIKE '%SqlExecution%');

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.LLM_CALLS AS
SELECT
    e.TIMESTAMP                                         AS call_time,
    e.START_TIMESTAMP                                   AS start_time,
    DATEDIFF('millisecond', e.START_TIMESTAMP, e.TIMESTAMP) AS duration_ms,
    e.TRACE:trace_id::STRING                            AS trace_id,
    e.RECORD:name::STRING                               AS span_name,
    e.RECORD:status.code::STRING                        AS status_code,
    e.RECORD_ATTRIBUTES                                 AS attributes
FROM snowflake.local.ai_observability_events e
WHERE e.RECORD_TYPE = 'SPAN'
  AND e.SCOPE:name::STRING IS DISTINCT FROM 'snow.cortex.agent'
  AND e.RECORD:name::STRING = 'ai.observability.llm.span';

-- ============================================================================
-- MONITORING VIEWS (trend analysis over the monitoring tables above)
-- ============================================================================

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_EVAL_ACCURACY_TREND AS
SELECT
    run_timestamp::DATE                         AS eval_date,
    'semantic_view'                             AS eval_type,
    environment,
    semantic_view_name                          AS target_name,
    accuracy_pct,
    threshold_pct,
    passed_threshold,
    total_questions,
    passed_questions,
    git_commit_sha,
    git_branch,
    LAG(accuracy_pct) OVER (
        PARTITION BY environment, semantic_view_name
        ORDER BY run_timestamp
    )                                           AS prev_accuracy_pct,
    accuracy_pct - COALESCE(LAG(accuracy_pct) OVER (
        PARTITION BY environment, semantic_view_name
        ORDER BY run_timestamp
    ), accuracy_pct)                            AS accuracy_delta,
    run_timestamp
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.SEMANTIC_VIEW_EVAL_RUNS

UNION ALL

SELECT
    run_timestamp::DATE                         AS eval_date,
    run_type                                    AS eval_type,
    environment,
    target_name,
    accuracy_pct,
    threshold_pct,
    passed_threshold,
    total_questions,
    passed_questions,
    NULL                                        AS git_commit_sha,
    NULL                                        AS git_branch,
    LAG(accuracy_pct) OVER (
        PARTITION BY environment, target_name, run_type
        ORDER BY run_timestamp
    )                                           AS prev_accuracy_pct,
    accuracy_pct - COALESCE(LAG(accuracy_pct) OVER (
        PARTITION BY environment, target_name, run_type
        ORDER BY run_timestamp
    ), accuracy_pct)                            AS accuracy_delta,
    run_timestamp
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.SCHEDULED_EVAL_RUNS;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_FEEDBACK_TREND AS
SELECT
    summary_date,
    environment,
    agent_or_sv_name,
    total_feedback,
    positive_count,
    neutral_count,
    negative_count,
    avg_rating,
    avg_sentiment_score,
    negative_pct,
    AVG(avg_rating) OVER (
        PARTITION BY environment, agent_or_sv_name
        ORDER BY summary_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                           AS rolling_7d_avg_rating,
    AVG(negative_pct) OVER (
        PARTITION BY environment, agent_or_sv_name
        ORDER BY summary_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                           AS rolling_7d_negative_pct,
    SUM(total_feedback) OVER (
        PARTITION BY environment, agent_or_sv_name
        ORDER BY summary_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                           AS rolling_7d_total_feedback,
    feedback_categories
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.FEEDBACK_DAILY_SUMMARY;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_TOKEN_COST_TREND AS
SELECT
    metric_date,
    environment,
    service_type,
    agent_or_sv_name,
    total_requests,
    successful_requests,
    failed_requests,
    total_input_tokens,
    total_output_tokens,
    total_tokens,
    estimated_credits,
    avg_latency_ms,
    p95_latency_ms,
    unique_users,
    SUM(total_tokens) OVER (
        PARTITION BY environment, service_type, agent_or_sv_name
        ORDER BY metric_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                           AS rolling_7d_tokens,
    SUM(estimated_credits) OVER (
        PARTITION BY environment, service_type, agent_or_sv_name
        ORDER BY metric_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                           AS rolling_7d_credits,
    AVG(avg_latency_ms) OVER (
        PARTITION BY environment, service_type, agent_or_sv_name
        ORDER BY metric_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    )                                           AS rolling_7d_avg_latency_ms,
    SUM(total_requests) OVER (
        PARTITION BY environment, service_type, agent_or_sv_name
        ORDER BY metric_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    )                                           AS rolling_30d_requests,
    SUM(estimated_credits) OVER (
        PARTITION BY environment, service_type, agent_or_sv_name
        ORDER BY metric_date
        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
    )                                           AS rolling_30d_credits,
    ROUND(
        COALESCE(failed_requests, 0) * 100.0 / NULLIF(total_requests, 0), 2
    )                                           AS error_rate_pct
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_AGENT_USAGE_PATTERNS AS
SELECT
    event_time::DATE                                                AS usage_date,
    HOUR(event_time)                                                AS usage_hour,
    DAYNAME(event_time)                                             AS day_of_week,
    COALESCE(database_name, 'UNKNOWN')                              AS environment,
    CASE
        WHEN span_name LIKE 'ReasoningAgentStep%' OR span_name LIKE 'CodingAgent%' THEN 'cortex_agent'
        WHEN span_name ILIKE '%Analyst%' OR span_name ILIKE '%SqlExecution%' THEN 'cortex_analyst'
        ELSE 'other'
    END                                                             AS service_type,
    agent_name,
    model_used,
    COUNT(*)                                                        AS span_count,
    COUNT(DISTINCT trace_id)                                        AS request_count,
    SUM(COALESCE(total_tokens, 0))                                  AS total_tokens,
    AVG(planning_duration_ms)                                       AS avg_latency_ms,
    COUNT_IF(status_code != 'STATUS_CODE_OK')                       AS error_count
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.AGENT_TRACES
GROUP BY 1, 2, 3, 4, 5, 6, 7;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_HEALTH_DASHBOARD AS
SELECT *
FROM (
    SELECT
        check_name,
        environment,
        target_name,
        status,
        details,
        latency_ms,
        checked_at,
        ROW_NUMBER() OVER (
            PARTITION BY check_name, environment, target_name
            ORDER BY checked_at DESC
        ) AS rn
    FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.HEALTH_CHECK_RESULTS
)
WHERE rn = 1;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_ACTIVE_ALERTS AS
SELECT
    alert_id,
    alert_type,
    severity,
    environment,
    target_name,
    message,
    metric_value,
    threshold_value,
    created_at,
    DATEDIFF('hour', created_at, CURRENT_TIMESTAMP()) AS hours_since_created
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
WHERE acknowledged = FALSE
ORDER BY
    CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'WARNING' THEN 1 ELSE 2 END,
    created_at DESC;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_WEEKLY_EXECUTIVE_SUMMARY AS
SELECT
    DATE_TRUNC('week', metric_date)                     AS week_start,
    environment,
    SUM(total_requests)                                 AS total_requests,
    SUM(successful_requests)                            AS successful_requests,
    ROUND(SUM(successful_requests) * 100.0 / NULLIF(SUM(total_requests), 0), 2) AS success_rate_pct,
    SUM(total_tokens)                                   AS total_tokens,
    SUM(estimated_credits)                              AS total_credits,
    AVG(avg_latency_ms)                                 AS avg_latency_ms,
    SUM(unique_users)                                   AS total_user_sessions
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS
GROUP BY 1, 2;

-- ============================================================================
-- INTERACTION QUALITY ENGINE
-- Rules-based detection of problematic agent interactions (no LLM needed):
--   1. Tool call looping       (same tool called 3+ times in one request)
--   2. Excessive planning steps (4+ steps to resolve a query)
--   3. Slow requests           (total duration > 60s)
--   4. High token burn         (>100k tokens in a single request)
--   5. Planning errors         (any step with planning_status = 'ERROR')
--   6. Abandoned conversations (thread with 3+ turns, no follow-up in 30min)
--   7. Single-turn drop-off    (thread with exactly 1 turn)
--   8. Repeated rephrasing     (3+ messages in a thread quickly)
-- ============================================================================

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_REQUEST_QUALITY_SIGNALS AS
WITH request_spans AS (
    SELECT
        TRACE:trace_id::STRING                                                              AS trace_id,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.thread_id"::STRING                   AS thread_id,
        RECORD_ATTRIBUTES:"snow.ai.observability.database.name"::STRING                     AS database_name,
        RECORD_ATTRIBUTES:"snow.ai.observability.schema.name"::STRING                       AS schema_name,
        RECORD_ATTRIBUTES:"snow.ai.observability.object.name"::STRING                       AS agent_name,
        RECORD:name::STRING                                                                 AS span_name,
        RECORD:status.code::STRING                                                          AS status_code,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.status"::STRING             AS planning_status,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.step_number"::INTEGER       AS step_number,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.token_count.total"::INTEGER AS step_tokens,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.duration"::FLOAT            AS step_duration_ms,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.tool_selection.name"::STRING AS tool_selected,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.query"::STRING              AS user_query,
        START_TIMESTAMP,
        TIMESTAMP AS end_timestamp
    FROM snowflake.local.ai_observability_events
    WHERE RECORD_TYPE = 'SPAN'
      AND SCOPE:name::STRING = 'snow.cortex.agent'
      AND RECORD:name::STRING LIKE 'ReasoningAgentStepPlanning%'
),
tool_counts AS (
    SELECT
        trace_id,
        tool_selected,
        COUNT(*) AS call_count
    FROM request_spans
    WHERE tool_selected IS NOT NULL
    GROUP BY 1, 2
)
SELECT
    r.trace_id,
    MAX(r.thread_id)                                                    AS thread_id,
    MAX(r.database_name)                                                AS database_name,
    MAX(r.schema_name)                                                  AS schema_name,
    MAX(r.agent_name)                                                   AS agent_name,
    MAX(r.user_query)                                                   AS user_query,
    MIN(r.START_TIMESTAMP)                                              AS request_start,
    MAX(r.end_timestamp)                                                AS request_end,
    DATEDIFF('millisecond', MIN(r.START_TIMESTAMP), MAX(r.end_timestamp)) AS total_duration_ms,

    MAX(r.step_number)                                                  AS max_step,
    SUM(COALESCE(r.step_tokens, 0))                                     AS total_tokens,
    COUNT_IF(r.planning_status = 'ERROR')                               AS error_step_count,
    MAX(COALESCE(tc.max_same_tool_calls, 0))                            AS max_same_tool_calls,

    -- FLAGS
    IFF(MAX(COALESCE(tc.max_same_tool_calls, 0)) >= 3, TRUE, FALSE)     AS flag_tool_looping,
    IFF(MAX(r.step_number) >= 4, TRUE, FALSE)                           AS flag_excessive_steps,
    IFF(DATEDIFF('millisecond', MIN(r.START_TIMESTAMP), MAX(r.end_timestamp)) > 60000, TRUE, FALSE) AS flag_slow_request,
    IFF(SUM(COALESCE(r.step_tokens, 0)) > 100000, TRUE, FALSE)         AS flag_high_token_burn,
    IFF(COUNT_IF(r.planning_status = 'ERROR') > 0, TRUE, FALSE)        AS flag_planning_error,

    (IFF(MAX(COALESCE(tc.max_same_tool_calls, 0)) >= 3, 1, 0)
     + IFF(MAX(r.step_number) >= 4, 1, 0)
     + IFF(DATEDIFF('millisecond', MIN(r.START_TIMESTAMP), MAX(r.end_timestamp)) > 60000, 1, 0)
     + IFF(SUM(COALESCE(r.step_tokens, 0)) > 100000, 1, 0)
     + IFF(COUNT_IF(r.planning_status = 'ERROR') > 0, 1, 0))           AS flag_count

FROM request_spans r
LEFT JOIN (
    SELECT trace_id, MAX(call_count) AS max_same_tool_calls
    FROM tool_counts
    GROUP BY 1
) tc ON r.trace_id = tc.trace_id
GROUP BY r.trace_id;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_THREAD_QUALITY_SIGNALS AS
WITH thread_turns AS (
    SELECT
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.thread_id"::STRING   AS thread_id,
        TRACE:trace_id::STRING                                               AS trace_id,
        RECORD_ATTRIBUTES:"snow.ai.observability.object.name"::STRING        AS agent_name,
        RECORD_ATTRIBUTES:"snow.ai.observability.database.name"::STRING      AS database_name,
        RECORD_ATTRIBUTES:"snow.ai.observability.agent.planning.query"::STRING AS user_query,
        MIN(START_TIMESTAMP)                                                 AS turn_start,
        MAX(TIMESTAMP)                                                       AS turn_end
    FROM snowflake.local.ai_observability_events
    WHERE RECORD_TYPE = 'SPAN'
      AND SCOPE:name::STRING = 'snow.cortex.agent'
      AND RECORD:name::STRING = 'ReasoningAgentStepPlanning-0'
      AND RECORD_ATTRIBUTES:"snow.ai.observability.agent.thread_id" IS NOT NULL
    GROUP BY 1, 2, 3, 4, 5
),
thread_summary AS (
    SELECT
        thread_id,
        MAX(agent_name)                                             AS agent_name,
        MAX(database_name)                                          AS database_name,
        COUNT(DISTINCT trace_id)                                    AS turn_count,
        MIN(turn_start)                                             AS first_turn,
        MAX(turn_end)                                               AS last_turn,
        DATEDIFF('minute', MIN(turn_start), MAX(turn_end))          AS conversation_duration_min,
        AVG(DATEDIFF('second', turn_start, turn_end))               AS avg_turn_duration_sec
    FROM thread_turns
    GROUP BY thread_id
)
SELECT
    thread_id,
    agent_name,
    database_name,
    turn_count,
    first_turn,
    last_turn,
    conversation_duration_min,
    avg_turn_duration_sec,

    -- FLAGS
    IFF(turn_count = 1, TRUE, FALSE)                                            AS flag_single_turn_dropoff,
    IFF(turn_count >= 3 AND conversation_duration_min <= 5, TRUE, FALSE)        AS flag_rapid_rephrasing,
    IFF(turn_count >= 3
        AND DATEDIFF('minute', last_turn, CURRENT_TIMESTAMP()) > 30
        AND conversation_duration_min < 60, TRUE, FALSE)                        AS flag_abandoned_conversation,

    (IFF(turn_count = 1, 1, 0)
     + IFF(turn_count >= 3 AND conversation_duration_min <= 5, 1, 0)
     + IFF(turn_count >= 3
           AND DATEDIFF('minute', last_turn, CURRENT_TIMESTAMP()) > 30
           AND conversation_duration_min < 60, 1, 0))                          AS flag_count

FROM thread_summary;

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_INTERACTION_QUALITY_FLAGS AS
SELECT signal_source, interaction_id, thread_id, environment,
       agent_name, user_query, event_time, total_duration_ms,
       total_tokens, steps, severity,
       flag_tool_looping, flag_excessive_steps, flag_slow_request,
       flag_high_token_burn, flag_planning_error
FROM (
    SELECT
        'request' AS signal_source,
        trace_id AS interaction_id,
        thread_id,
        database_name AS environment,
        agent_name,
        user_query,
        request_start AS event_time,
        total_duration_ms,
        total_tokens,
        max_step AS steps,
        flag_tool_looping,
        flag_excessive_steps,
        flag_slow_request,
        flag_high_token_burn,
        flag_planning_error,
        CASE
            WHEN flag_planning_error THEN 'CRITICAL'
            WHEN flag_tool_looping AND flag_high_token_burn THEN 'CRITICAL'
            WHEN flag_tool_looping OR flag_excessive_steps THEN 'WARNING'
            WHEN flag_slow_request OR flag_high_token_burn THEN 'WARNING'
            ELSE 'INFO'
        END AS severity
    FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_REQUEST_QUALITY_SIGNALS
    WHERE flag_count > 0
) sub
WHERE agent_name IS NOT NULL;

CREATE TABLE IF NOT EXISTS {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.INTERACTION_QUALITY_DAILY (
    summary_date            DATE,
    environment             STRING,
    agent_name              STRING,
    total_requests          INTEGER,
    total_threads           INTEGER,
    flagged_requests        INTEGER,
    flagged_threads         INTEGER,
    tool_looping_count      INTEGER,
    excessive_steps_count   INTEGER,
    slow_request_count      INTEGER,
    high_token_burn_count   INTEGER,
    planning_error_count    INTEGER,
    single_turn_dropoff_count INTEGER,
    rapid_rephrasing_count  INTEGER,
    abandoned_count         INTEGER,
    critical_count          INTEGER,
    warning_count           INTEGER,
    flagged_request_pct     FLOAT,
    computed_at             TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

CREATE OR REPLACE VIEW {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_INTERACTION_QUALITY_DASHBOARD AS
SELECT
    summary_date,
    environment,
    agent_name,
    total_requests,
    total_threads,
    flagged_requests,
    flagged_request_pct,
    tool_looping_count,
    excessive_steps_count,
    slow_request_count,
    high_token_burn_count,
    planning_error_count,
    single_turn_dropoff_count,
    rapid_rephrasing_count,
    abandoned_count,
    critical_count,
    warning_count,
    AVG(flagged_request_pct) OVER (
        PARTITION BY environment, agent_name
        ORDER BY summary_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7d_flagged_pct,
    SUM(flagged_requests) OVER (
        PARTITION BY environment, agent_name
        ORDER BY summary_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7d_flagged_count,
    SUM(abandoned_count + rapid_rephrasing_count) OVER (
        PARTITION BY environment, agent_name
        ORDER BY summary_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7d_user_struggle_count
FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.INTERACTION_QUALITY_DAILY;

-- ============================================================================
-- MONITORING ALERTS
-- Snowflake Alerts that fire when monitoring thresholds are breached.
-- Each alert inserts into ALERT_HISTORY for tracking.
--
-- NOTE: Tasks and Alerts require {{WAREHOUSE}} placeholder for the warehouse.
-- ============================================================================

-- Alert: Negative feedback spike (>25% negative in a day)
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_NEGATIVE_FEEDBACK_SPIKE
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 7 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.FEEDBACK_DAILY_SUMMARY
        WHERE summary_date = CURRENT_DATE() - 1
          AND negative_pct > 25
          AND total_feedback >= 5
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'negative_feedback_spike',
            CASE WHEN negative_pct > 50 THEN 'CRITICAL' ELSE 'WARNING' END,
            environment,
            agent_or_sv_name,
            'Negative feedback spike: ' || ROUND(negative_pct, 1) || '% negative (' ||
                negative_count || '/' || total_feedback || '). Avg rating: ' || ROUND(avg_rating, 1),
            negative_pct,
            25
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.FEEDBACK_DAILY_SUMMARY
        WHERE summary_date = CURRENT_DATE() - 1
          AND negative_pct > 25
          AND total_feedback >= 5;

-- Alert: Accuracy regression (>10% drop between eval runs)
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_ACCURACY_REGRESSION
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 8 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_EVAL_ACCURACY_TREND
        WHERE eval_date >= CURRENT_DATE() - 1
          AND accuracy_delta < -10
          AND prev_accuracy_pct IS NOT NULL
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'accuracy_regression',
            CASE WHEN accuracy_delta < -20 THEN 'CRITICAL' ELSE 'WARNING' END,
            environment,
            target_name,
            eval_type || ' accuracy regression: ' || ROUND(accuracy_pct, 1) || '% (was ' ||
                ROUND(prev_accuracy_pct, 1) || '%, delta: ' || ROUND(accuracy_delta, 1) || '%)',
            accuracy_delta,
            -10
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_EVAL_ACCURACY_TREND
        WHERE eval_date >= CURRENT_DATE() - 1
          AND accuracy_delta < -10
          AND prev_accuracy_pct IS NOT NULL;

-- Alert: Latency degradation (P95 > 30s)
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_LATENCY_DEGRADATION
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 7 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS
        WHERE metric_date = CURRENT_DATE() - 1
          AND p95_latency_ms > 30000
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'latency_degradation',
            CASE WHEN p95_latency_ms > 60000 THEN 'CRITICAL' ELSE 'WARNING' END,
            environment,
            agent_or_sv_name,
            service_type || ' P95 latency: ' || ROUND(p95_latency_ms / 1000, 1) || 's (avg: ' || ROUND(avg_latency_ms / 1000, 1) || 's)',
            p95_latency_ms,
            30000
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS
        WHERE metric_date = CURRENT_DATE() - 1
          AND p95_latency_ms > 30000;

-- Alert: Cost anomaly (daily cost > 2x 7-day average)
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_COST_ANOMALY
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 7 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_TOKEN_COST_TREND
        WHERE metric_date = CURRENT_DATE() - 1
          AND rolling_7d_credits > 0
          AND estimated_credits > (rolling_7d_credits / 7.0) * 2
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'cost_anomaly',
            CASE WHEN estimated_credits > (rolling_7d_credits / 7.0) * 5 THEN 'CRITICAL' ELSE 'WARNING' END,
            environment,
            agent_or_sv_name,
            service_type || ' credit anomaly: ' || ROUND(estimated_credits, 4) || ' credits (' ||
                ROUND(estimated_credits / NULLIF(rolling_7d_credits / 7.0, 0), 1) || 'x normal)',
            estimated_credits,
            ROUND(rolling_7d_credits / 7.0 * 2, 4)
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_TOKEN_COST_TREND
        WHERE metric_date = CURRENT_DATE() - 1
          AND rolling_7d_credits > 0
          AND estimated_credits > (rolling_7d_credits / 7.0) * 2;

-- Alert: Agent error spike (error rate > 10%)
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_ERROR_SPIKE
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 7 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS
        WHERE metric_date = CURRENT_DATE() - 1
          AND total_requests >= 10
          AND ROUND(failed_requests * 100.0 / NULLIF(total_requests, 0), 2) > 10
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'error_spike',
            CASE WHEN ROUND(failed_requests * 100.0 / NULLIF(total_requests, 0), 2) > 25 THEN 'CRITICAL' ELSE 'WARNING' END,
            environment,
            agent_or_sv_name,
            service_type || ' error rate: ' || ROUND(failed_requests * 100.0 / NULLIF(total_requests, 0), 1) ||
                '% (' || failed_requests || ' failures / ' || total_requests || ' total)',
            ROUND(failed_requests * 100.0 / NULLIF(total_requests, 0), 2),
            10
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS
        WHERE metric_date = CURRENT_DATE() - 1
          AND total_requests >= 10
          AND ROUND(failed_requests * 100.0 / NULLIF(total_requests, 0), 2) > 10;

-- Alert: Health check failure
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HEALTH_FAILURE
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 30 6 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_HEALTH_DASHBOARD
        WHERE status = 'UNHEALTHY'
          AND checked_at >= DATEADD('hour', -25, CURRENT_TIMESTAMP())
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'health_failure',
            'CRITICAL',
            environment,
            target_name,
            'Health check FAILED: ' || check_name || ' - ' || details,
            0,
            0
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_HEALTH_DASHBOARD
        WHERE status = 'UNHEALTHY'
          AND checked_at >= DATEADD('hour', -25, CURRENT_TIMESTAMP());

-- Alert: Interaction quality degradation (>20% flagged OR any critical)
CREATE OR REPLACE ALERT {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_INTERACTION_QUALITY
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 7 * * * UTC'
    IF (EXISTS (
        SELECT 1
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.INTERACTION_QUALITY_DAILY
        WHERE summary_date = CURRENT_DATE() - 1
          AND (flagged_request_pct > 20 OR critical_count > 0)
          AND total_requests >= 5
    ))
    THEN
        INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.ALERT_HISTORY
            (alert_type, severity, environment, target_name, message, metric_value, threshold_value)
        SELECT
            'interaction_quality',
            CASE WHEN critical_count > 0 THEN 'CRITICAL' ELSE 'WARNING' END,
            environment,
            agent_name,
            'Interaction quality issues: ' || flagged_requests || '/' || total_requests || ' requests flagged (' ||
                ROUND(flagged_request_pct, 1) || '%). Looping: ' || tool_looping_count ||
                ', Steps: ' || excessive_steps_count || ', Slow: ' || slow_request_count ||
                ', High burn: ' || high_token_burn_count || ', Errors: ' || planning_error_count,
            flagged_request_pct,
            20
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.INTERACTION_QUALITY_DAILY
        WHERE summary_date = CURRENT_DATE() - 1
          AND (flagged_request_pct > 20 OR critical_count > 0)
          AND total_requests >= 5;

-- ============================================================================
-- MONITORING TASKS
-- Scheduled tasks for automated data collection.
-- ============================================================================

-- Task: Daily usage & token cost aggregation from observability events
CREATE OR REPLACE TASK {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.TASK_DAILY_USAGE_AGGREGATION
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 0 2 * * * UTC'
    COMMENT = 'Daily aggregation of agent/analyst usage and token costs'
AS
    INSERT INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USAGE_METRICS (
        metric_date, environment, service_type, agent_or_sv_name,
        total_requests, successful_requests, failed_requests,
        total_input_tokens, total_output_tokens, total_tokens, total_cache_read_tokens,
        estimated_credits, avg_latency_ms, p50_latency_ms, p95_latency_ms, p99_latency_ms,
        unique_users
    )
    SELECT
        CURRENT_DATE() - 1                                                           AS metric_date,
        COALESCE(database_name, 'UNKNOWN')                                           AS environment,
        CASE
            WHEN span_name LIKE 'ReasoningAgentStep%' OR span_name LIKE 'CodingAgent%' THEN 'cortex_agent'
            WHEN span_name ILIKE '%Analyst%' OR span_name ILIKE '%SqlExecution%' THEN 'cortex_analyst'
            ELSE 'other'
        END                                                                          AS service_type,
        COALESCE(agent_name, 'unknown')                                              AS agent_or_sv_name,
        COUNT(DISTINCT trace_id)                                                     AS total_requests,
        COUNT_IF(status_code = 'STATUS_CODE_OK')                                     AS successful_requests,
        COUNT_IF(status_code != 'STATUS_CODE_OK')                                    AS failed_requests,
        COALESCE(SUM(input_tokens), 0)                                               AS total_input_tokens,
        COALESCE(SUM(output_tokens), 0)                                              AS total_output_tokens,
        COALESCE(SUM(total_tokens), 0)                                               AS total_tokens,
        COALESCE(SUM(cache_read_tokens), 0)                                          AS total_cache_read_tokens,
        SUM(COALESCE(total_tokens, 0)) / 1000000.0 * 1.0                             AS estimated_credits,
        AVG(planning_duration_ms)                                                    AS avg_latency_ms,
        APPROX_PERCENTILE(planning_duration_ms, 0.5)                                 AS p50_latency_ms,
        APPROX_PERCENTILE(planning_duration_ms, 0.95)                                AS p95_latency_ms,
        APPROX_PERCENTILE(planning_duration_ms, 0.99)                                AS p99_latency_ms,
        0                                                                            AS unique_users
    FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.AGENT_TRACES
    WHERE event_time >= DATEADD('day', -1, CURRENT_DATE())
      AND event_time < CURRENT_DATE()
      AND (span_name LIKE 'ReasoningAgentStepPlanning%'
           OR span_name LIKE 'CodingAgent.Step%'
           OR span_name ILIKE '%Analyst%')
    GROUP BY 1, 2, 3, 4;

-- Task: Daily feedback sentiment analysis + rollup
CREATE OR REPLACE TASK {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.TASK_DAILY_FEEDBACK_ANALYSIS
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 15 2 * * * UTC'
    COMMENT = 'Daily feedback sentiment scoring and summary rollup'
AS
    MERGE INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.FEEDBACK_DAILY_SUMMARY tgt
    USING (
        SELECT
            created_at::DATE                                             AS summary_date,
            environment,
            agent_or_sv_name,
            COUNT(*)                                                     AS total_feedback,
            COUNT_IF(feedback_rating >= 4)                               AS positive_count,
            COUNT_IF(feedback_rating = 3)                                AS neutral_count,
            COUNT_IF(feedback_rating <= 2)                               AS negative_count,
            AVG(feedback_rating)                                         AS avg_rating,
            AVG(sentiment_score)                                         AS avg_sentiment_score,
            ROUND(COUNT_IF(feedback_rating <= 2) * 100.0 / NULLIF(COUNT(*), 0), 2) AS negative_pct
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.USER_FEEDBACK
        WHERE created_at::DATE = CURRENT_DATE() - 1
        GROUP BY 1, 2, 3
    ) src
    ON tgt.summary_date = src.summary_date
       AND tgt.environment = src.environment
       AND tgt.agent_or_sv_name = src.agent_or_sv_name
    WHEN MATCHED THEN UPDATE SET
        tgt.total_feedback = src.total_feedback,
        tgt.positive_count = src.positive_count,
        tgt.neutral_count = src.neutral_count,
        tgt.negative_count = src.negative_count,
        tgt.avg_rating = src.avg_rating,
        tgt.avg_sentiment_score = src.avg_sentiment_score,
        tgt.negative_pct = src.negative_pct,
        tgt.computed_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT (
        summary_date, environment, agent_or_sv_name,
        total_feedback, positive_count, neutral_count, negative_count,
        avg_rating, avg_sentiment_score, negative_pct
    ) VALUES (
        src.summary_date, src.environment, src.agent_or_sv_name,
        src.total_feedback, src.positive_count, src.neutral_count, src.negative_count,
        src.avg_rating, src.avg_sentiment_score, src.negative_pct
    );

-- Task: Daily interaction quality scan
CREATE OR REPLACE TASK {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.TASK_DAILY_INTERACTION_QUALITY
    WAREHOUSE = {{WAREHOUSE}}
    SCHEDULE = 'USING CRON 30 2 * * * UTC'
    COMMENT = 'Daily scan of agent interactions for quality issues'
AS
    MERGE INTO {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.INTERACTION_QUALITY_DAILY tgt
    USING (
        SELECT
            CURRENT_DATE() - 1                                          AS summary_date,
            database_name                                               AS environment,
            agent_name,
            COUNT(*)                                                     AS total_requests,
            0                                                           AS total_threads,
            COUNT_IF(flag_count > 0)                                     AS flagged_requests,
            0                                                           AS flagged_threads,
            COUNT_IF(flag_tool_looping)                                  AS tool_looping_count,
            COUNT_IF(flag_excessive_steps)                               AS excessive_steps_count,
            COUNT_IF(flag_slow_request)                                  AS slow_request_count,
            COUNT_IF(flag_high_token_burn)                               AS high_token_burn_count,
            COUNT_IF(flag_planning_error)                                AS planning_error_count,
            0                                                           AS single_turn_dropoff_count,
            0                                                           AS rapid_rephrasing_count,
            0                                                           AS abandoned_count,
            COUNT_IF(flag_planning_error OR (flag_tool_looping AND flag_high_token_burn)) AS critical_count,
            COUNT_IF(flag_count > 0 AND NOT (flag_planning_error OR (flag_tool_looping AND flag_high_token_burn))) AS warning_count,
            ROUND(COUNT_IF(flag_count > 0) * 100.0 / NULLIF(COUNT(*), 0), 2) AS flagged_request_pct
        FROM {{FRAMEWORK_DB}}.{{FRAMEWORK_SCHEMA}}.V_REQUEST_QUALITY_SIGNALS
        WHERE request_start >= DATEADD('day', -1, CURRENT_DATE())
          AND request_start < CURRENT_DATE()
        GROUP BY 1, 2, 3
    ) src
    ON tgt.summary_date = src.summary_date
       AND tgt.environment = src.environment
       AND tgt.agent_name = src.agent_name
    WHEN MATCHED THEN UPDATE SET
        tgt.total_requests = src.total_requests,
        tgt.flagged_requests = src.flagged_requests,
        tgt.tool_looping_count = src.tool_looping_count,
        tgt.excessive_steps_count = src.excessive_steps_count,
        tgt.slow_request_count = src.slow_request_count,
        tgt.high_token_burn_count = src.high_token_burn_count,
        tgt.planning_error_count = src.planning_error_count,
        tgt.critical_count = src.critical_count,
        tgt.warning_count = src.warning_count,
        tgt.flagged_request_pct = src.flagged_request_pct,
        tgt.computed_at = CURRENT_TIMESTAMP()
    WHEN NOT MATCHED THEN INSERT (
        summary_date, environment, agent_name,
        total_requests, total_threads, flagged_requests, flagged_threads,
        tool_looping_count, excessive_steps_count, slow_request_count,
        high_token_burn_count, planning_error_count,
        single_turn_dropoff_count, rapid_rephrasing_count, abandoned_count,
        critical_count, warning_count, flagged_request_pct
    ) VALUES (
        src.summary_date, src.environment, src.agent_name,
        src.total_requests, src.total_threads, src.flagged_requests, src.flagged_threads,
        src.tool_looping_count, src.excessive_steps_count, src.slow_request_count,
        src.high_token_burn_count, src.planning_error_count,
        src.single_turn_dropoff_count, src.rapid_rephrasing_count, src.abandoned_count,
        src.critical_count, src.warning_count, src.flagged_request_pct
    );
