"""Diagnostic commands: each one builds a single SELECT over system tables."""

from __future__ import annotations

import re

SYSTEM_DATABASES = "('system', 'INFORMATION_SCHEMA', 'information_schema')"
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Cluster names are string literals, so `mongodb-logs` is valid; quotes and backslashes are not.
_CLUSTER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_DURATION = re.compile(r"^(\d+)([smhd])$")
_UNITS = {"s": "SECOND", "m": "MINUTE", "h": "HOUR", "d": "DAY"}


def ident(name: str) -> str:
    """Quote an identifier after checking it, so user input never reaches the SQL as code."""
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return f"`{name}`"


def table_ref(name: str) -> tuple[str | None, str]:
    """`db.table` or `table` -> (database or None, table)."""
    parts = name.split(".")
    if len(parts) > 2:
        raise ValueError(f"invalid table name: {name!r}")
    for part in parts:
        ident(part)
    return (parts[0], parts[1]) if len(parts) == 2 else (None, parts[0])


def interval(duration: str) -> str:
    """`30m` -> `INTERVAL 30 MINUTE`."""
    match = _DURATION.match(duration)
    if not match:
        raise ValueError(f"invalid duration {duration!r}, expected e.g. 90s, 30m, 1h, 7d")
    return f"INTERVAL {match.group(1)} {_UNITS[match.group(2)]}"


def cluster_name(name: str) -> str:
    if not _CLUSTER.match(name):
        raise ValueError(f"invalid cluster name: {name!r}")
    return name


def source(table: str, cluster: str | None) -> str:
    """`system.<table>` on this server, or on every replica of `cluster`."""
    if cluster:
        return f"clusterAllReplicas('{cluster_name(cluster)}', system.{ident(table)[1:-1]})"
    return f"system.{ident(table)[1:-1]}"


def _db_filter(column: str, database: str | None) -> str:
    if database:
        return f"{column} = '{ident(database)[1:-1]}'"
    return f"{column} NOT IN {SYSTEM_DATABASES}"


def health() -> str:
    # Scalar subqueries run on the server that receives the query, so this reports one server.
    return """SELECT
    hostName() AS host,
    version() AS version,
    formatReadableTimeDelta(uptime()) AS uptime,
    (SELECT count() FROM system.replicas WHERE is_readonly) AS readonly_replicas,
    (SELECT max(absolute_delay) FROM system.replicas) AS max_replica_delay_s,
    (SELECT max(round(100 * (1 - free_space / total_space), 1)) FROM system.disks) AS disk_used_pct,
    (SELECT count() FROM system.mutations WHERE NOT is_done) AS pending_mutations,
    (SELECT count() FROM system.mutations WHERE NOT is_done AND latest_fail_reason != '')
        AS failing_mutations,
    (SELECT count() FROM system.merges) AS running_merges,
    (SELECT count() FROM system.processes) AS running_queries
FROM system.one"""


def tables(database: str | None = None, limit: int = 50) -> str:
    return f"""SELECT
    t.database AS database,
    t.name AS table,
    t.engine AS engine,
    -- Views have no rows, size or parts: show empty cells, not NULL and 1970-01-01.
    ifNull(toString(t.total_rows), '') AS rows,
    if(t.total_bytes IS NULL, '', formatReadableSize(t.total_bytes)) AS size,
    if(p.parts = 0, '', toString(p.parts)) AS parts,
    if(p.parts = 0, '', toString(p.last_write)) AS last_write,
    extract(t.engine_full, 'TTL (.+?)(?: SETTINGS |$)') AS ttl
FROM system.tables AS t
LEFT JOIN (
    SELECT database, table, count() AS parts, max(modification_time) AS last_write
    FROM system.parts
    WHERE active
    GROUP BY database, table
) AS p ON p.database = t.database AND p.table = t.name
WHERE {_db_filter("t.database", database)}
ORDER BY t.total_bytes DESC NULLS LAST
LIMIT {int(limit)}"""


def fields(table: str, database: str | None = None) -> str:
    db, name = table_ref(table)
    db = db or database
    db_cond = f"database = '{db}'" if db else "database = currentDatabase()"
    return f"""SELECT
    name,
    type,
    default_kind,
    default_expression,
    compression_codec AS codec,
    formatReadableSize(data_compressed_bytes) AS compressed,
    formatReadableSize(data_uncompressed_bytes) AS uncompressed,
    round(data_uncompressed_bytes / nullIf(data_compressed_bytes, 0), 1) AS ratio,
    is_in_sorting_key AS in_sorting_key
FROM system.columns
WHERE {db_cond} AND table = '{name}'
ORDER BY position"""


def disk(cluster: str | None = None) -> str:
    return f"""SELECT
    hostName() AS host,
    name,
    path,
    formatReadableSize(free_space) AS free,
    formatReadableSize(total_space) AS total,
    round(100 * (1 - free_space / total_space), 1) AS used_pct
FROM {source("disks", cluster)}
ORDER BY host, name"""


def fresh(table: str, ts: str, window: str = "5m", database: str | None = None, lookback: str = "1d") -> str:
    db, name = table_ref(table)
    db = db or database
    target = f"{ident(db)}.{ident(name)}" if db else ident(name)
    column = ident(ts)
    return f"""SELECT
    max({column}) AS last,
    dateDiff('second', max({column}), now()) AS lag_s,
    countIf({column} > now() - {interval(window)}) AS rows_in_window
FROM {target}
-- Bounded so the scan prunes partitions; no rows in the lookback gives a NULL `last`.
WHERE {column} > now() - {interval(lookback)}"""


def replicas(problems_only: bool = False, cluster: str | None = None, min_delay: int = 60) -> str:
    # A few seconds of delay and a short queue are normal while inserts keep arriving.
    where = (
        f"WHERE is_readonly OR is_session_expired OR absolute_delay > {int(min_delay)} OR queue_size > 100"
        if problems_only
        else ""
    )
    return f"""SELECT
    hostName() AS host,
    database,
    table,
    is_leader,
    is_readonly,
    is_session_expired,
    absolute_delay,
    queue_size,
    inserts_in_queue,
    merges_in_queue,
    active_replicas,
    total_replicas
FROM {source("replicas", cluster)}
{where}
ORDER BY absolute_delay DESC, queue_size DESC, database, table"""


def mutations(include_done: bool = False, limit: int = 50, cluster: str | None = None) -> str:
    where = "" if include_done else "WHERE NOT is_done"
    return f"""SELECT
    hostName() AS host,
    database,
    table,
    mutation_id,
    left(command, 100) AS command,
    create_time,
    is_done,
    parts_to_do,
    latest_fail_reason
FROM {source("mutations", cluster)}
{where}
ORDER BY create_time DESC
LIMIT {int(limit)}"""


def merges(cluster: str | None = None) -> str:
    return f"""SELECT
    hostName() AS host,
    database,
    table,
    round(elapsed) AS elapsed_s,
    round(100 * progress, 1) AS progress_pct,
    num_parts,
    formatReadableSize(total_size_bytes_compressed) AS size,
    is_mutation,
    formatReadableSize(memory_usage) AS memory
FROM {source("merges", cluster)}
ORDER BY elapsed DESC"""


def slow(since: str = "1h", min_ms: int = 1000, limit: int = 20, cluster: str | None = None) -> str:
    return f"""SELECT
    hostName() AS host,
    event_time,
    user,
    query_duration_ms AS duration_ms,
    read_rows,
    formatReadableSize(read_bytes) AS read,
    formatReadableSize(memory_usage) AS memory,
    exception_code,
    left(replaceRegexpAll(query, '\\\\s+', ' '), 120) AS query
FROM {source("query_log", cluster)}
WHERE event_time > now() - {interval(since)}
  AND type IN ('QueryFinish', 'ExceptionWhileProcessing')
  AND query_duration_ms >= {int(min_ms)}
ORDER BY query_duration_ms DESC
LIMIT {int(limit)}"""
