# ch-cli

Small CLI for ClickHouse diagnostics over the HTTP interface: health, tables, replication, merges, mutations and slow queries, in one command each. No dependencies beyond the Python standard library.

> Status: early (v0.1).

## Install

```bash
uv tool install git+https://github.com/arekborucki/ch-cli
# or
pipx install git+https://github.com/arekborucki/ch-cli
```

Python 3.11+.

## Configure

Profiles live in `~/.config/ch-cli/config.toml` (`CH_CLI_CONFIG` overrides the path). See [examples/config.toml](examples/config.toml).

```toml
default = "prod"

[profiles.prod]
url = "http://clickhouse.example.internal:8123"
user = "readonly"
password_env = "CH_PROD_PASSWORD"   # or password_cmd = "<command that prints it>"
```

Passwords are never read from the file: a `password` key is rejected. Precedence for each value is flag, then environment, then profile:

| Value | Flag | Environment |
|---|---|---|
| profile | `-p, --profile` | `CH_PROFILE` |
| URL | `--url` | `CH_URL` |
| user | `--user` | `CH_USER` |
| password | | `CH_PASSWORD`, then `password_env`, then `password_cmd` |
| database | | `CH_DATABASE` |

Credentials are sent in the `X-ClickHouse-User` / `X-ClickHouse-Key` headers, not in the URL. Every query carries `log_comment = 'ch-cli/<version>'`, so it can be found in `system.query_log`.

Use a read-only user. A profile with `readonly = 2` still lets ch-cli set `log_comment`; fixed limits (`max_execution_time`, `max_result_rows`, `max_memory_usage`) are best enforced with `const` constraints, because `0` means unlimited and passes a `max` constraint.

## Commands

| Command | Shows |
|---|---|
| `ping` | whether the server answers (no auth) |
| `profiles` | configured profiles, `*` marks the default |
| `health` | version, uptime, readonly replicas, max replica delay, disk used %, pending/failing mutations, merges, running queries |
| `tables [-d DB] [-n N]` | tables by size: engine, rows, size, parts, last write, TTL |
| `fields TABLE` | columns: type, default, codec, compressed/uncompressed size, ratio, sorting key |
| `disk` | free/total/used % per disk |
| `fresh TABLE --ts COL [-w 5m]` | newest row, lag in seconds, rows in the window: is data still arriving? |
| `replicas [--problems]` | replication state per replicated table |
| `mutations [--all] [-n N]` | unfinished mutations (or recent ones) with the last failure |
| `merges` | running merges with progress and size |
| `slow [--since 1h] [--min-ms 1000] [-n N]` | slowest queries from `system.query_log` |
| `sql [QUERY]` | any query; reads stdin when omitted or `-` |

`disk`, `replicas`, `mutations`, `merges` and `slow` take `-c CLUSTER` to read every replica through `clusterAllReplicas` (a `host` column tells them apart). Without `-c` only the server behind the URL answers, which on a load-balanced service is a random replica, so use `-c` for `slow` and `mutations` on replicated clusters. `health` and `tables` always report the server that receives the query.

With `-H`, an empty result prints `(no rows)` on stderr; the default JSON output stays empty.

`--print-sql` prints the generated query instead of running it. Table and column names are validated and quoted, so they cannot inject SQL.

## Usage

```bash
ch-cli ping
ch-cli -p prod -H health
ch-cli -p prod -H tables -d analytics
ch-cli -p prod -H fields analytics.events
ch-cli -p prod -H fresh analytics.events --ts received_at -w 10m
ch-cli -p prod -H replicas -c main --problems
ch-cli -p prod -H slow --since 24h --min-ms 5000
ch-cli -p prod sql "SELECT version()" | jq
echo "SELECT 1" | ch-cli -p prod sql
ch-cli --print-sql slow
```

Output is `JSONEachRow` by default (one JSON object per line, easy to pipe into `jq`), `-H` prints a table, and `-f` takes any ClickHouse output format.

Exit codes: `0` success, `1` server or connection error (message on stderr), `2` configuration or argument error.

## License

Apache-2.0, see [LICENSE](LICENSE).

## Development

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```
