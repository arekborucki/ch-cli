"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from ch_cli import __version__, commands
from ch_cli.client import Client, QueryError
from ch_cli.config import ConfigError, config_path, load_config, profile_names, resolve_profile

HUMAN_FORMAT = "PrettyCompactMonoBlock"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ch-cli", description="ClickHouse diagnostics over the HTTP interface."
    )
    parser.add_argument("--version", action="version", version=f"ch-cli {__version__}")
    parser.add_argument(
        "-p", "--profile", help="profile from the config file (default: CH_PROFILE or `default`)"
    )
    parser.add_argument("--url", help="server URL, e.g. http://localhost:8123 (overrides the profile)")
    parser.add_argument("--user", help="user name (overrides the profile)")
    parser.add_argument("-H", "--human", action="store_true", help="human-readable table output")
    parser.add_argument("-f", "--format", help="any ClickHouse output format (overrides -H)")
    parser.add_argument("--timeout", type=float, default=130.0, help="HTTP timeout in seconds (default: 130)")
    parser.add_argument(
        "--print-sql", action="store_true", help="print the generated SQL instead of running it"
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def with_cluster(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("-c", "--cluster", help="query every replica of this cluster (clusterAllReplicas)")
        return p

    sub.add_parser("ping", help="check that the server answers")
    sub.add_parser("profiles", help="list configured profiles")
    sql = sub.add_parser("sql", help="run a query (read from stdin when omitted or `-`)")
    sql.add_argument("query", nargs="?", default="-")

    sub.add_parser("health", help="version, uptime, replicas, disk, mutations, merges in one row")
    p = sub.add_parser("tables", help="tables by size: rows, parts, last write, TTL")
    p.add_argument("-d", "--database", help="only this database (default: all non-system)")
    p.add_argument("-n", "--limit", type=int, default=50)
    p = sub.add_parser("fields", help="columns of a table: type, codec, compressed size, ratio")
    p.add_argument("table", help="table or db.table")
    p.add_argument("-d", "--database")
    with_cluster(sub.add_parser("disk", help="free and used space per disk"))
    p = sub.add_parser("fresh", help="is data still arriving? newest row, lag and rows in the window")
    p.add_argument("table", help="table or db.table")
    p.add_argument("--ts", required=True, help="timestamp column, e.g. received_at")
    p.add_argument("-w", "--window", default="5m", help="window for rows_in_window (default: 5m)")
    p.add_argument("--lookback", default="1d", help="only scan this far back (default: 1d)")
    p.add_argument("-d", "--database")
    p = with_cluster(sub.add_parser("replicas", help="replication state per replicated table"))
    p.add_argument(
        "--problems",
        action="store_true",
        help="only readonly, expired, delayed (> --min-delay) or queue > 100",
    )
    p.add_argument(
        "--min-delay", type=int, default=60, help="seconds of delay that count as a problem (default: 60)"
    )
    p = with_cluster(sub.add_parser("mutations", help="mutations not done yet (with --all: recent ones)"))
    p.add_argument("--all", action="store_true", dest="include_done")
    p.add_argument("-n", "--limit", type=int, default=50)
    with_cluster(sub.add_parser("merges", help="running merges"))
    p = with_cluster(sub.add_parser("slow", help="slowest queries from system.query_log"))
    p.add_argument("--since", default="1h", help="look back this far (default: 1h)")
    p.add_argument("--min-ms", type=int, default=1000, help="minimum duration (default: 1000)")
    p.add_argument("-n", "--limit", type=int, default=20)
    return parser


def build_sql(args: argparse.Namespace) -> str:
    cluster = getattr(args, "cluster", None)
    match args.command:
        case "health":
            return commands.health()
        case "tables":
            return commands.tables(args.database, args.limit)
        case "fields":
            return commands.fields(args.table, args.database)
        case "disk":
            return commands.disk(cluster)
        case "fresh":
            return commands.fresh(args.table, args.ts, args.window, args.database, args.lookback)
        case "replicas":
            return commands.replicas(args.problems, cluster, args.min_delay)
        case "mutations":
            return commands.mutations(args.include_done, args.limit, cluster)
        case "merges":
            return commands.merges(cluster)
        case "slow":
            return commands.slow(args.since, args.min_ms, args.limit, cluster)
        case "sql":
            return sys.stdin.read() if args.query == "-" else args.query
    raise AssertionError(args.command)


def output_format(args: argparse.Namespace) -> str:
    return args.format or (HUMAN_FORMAT if args.human else "JSONEachRow")


def run(args: argparse.Namespace) -> int:
    config = load_config()
    if args.command == "profiles":
        names = profile_names(config)
        if not names:
            print(f"no profiles in {config_path()}", file=sys.stderr)
            return 1
        for name in names:
            marker = "*" if name == config.get("default") else " "
            print(f"{marker} {name}\t{config['profiles'][name].get('url', '')}")
        return 0

    if args.command != "ping":
        sql = build_sql(args)
        if args.print_sql:
            print(sql)
            return 0

    client = Client(resolve_profile(config, args.profile, args.url, args.user), timeout=args.timeout)
    if args.command == "ping":
        print(client.ping())
        return 0
    fmt = output_format(args)
    result = client.query(sql, fmt)
    if result:
        sys.stdout.write(result)
    elif fmt.startswith("Pretty"):
        # Pretty formats print nothing for an empty result; say so on stderr, keeping stdout clean.
        print("(no rows)", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except QueryError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
