# ch-cli

Small CLI for ClickHouse diagnostics over the HTTP interface: health, tables, replication, merges, mutations and slow queries, in one command each. No dependencies beyond the Python standard library.

> Status: early. v0.1 ships `ping`, `sql` and `profiles`; the diagnostic commands come next.

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

## Usage

```bash
ch-cli ping
ch-cli profiles
ch-cli -p prod sql "SELECT version(), uptime()"
ch-cli -p prod -H sql "SELECT database, name, total_rows FROM system.tables LIMIT 5"
echo "SELECT 1" | ch-cli -p prod sql
ch-cli -p prod -f Vertical sql "SELECT * FROM system.disks"
```

Output is `JSONEachRow` by default (one JSON object per line, easy to pipe into `jq`), `-H` prints a table, and `-f` takes any ClickHouse output format.

Exit codes: `0` success, `1` server or connection error (message on stderr), `2` configuration error.

## Development

```bash
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
```
