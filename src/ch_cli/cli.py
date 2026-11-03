"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from ch_cli import __version__
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
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    sub.add_parser("ping", help="check that the server answers")
    sub.add_parser("profiles", help="list configured profiles")
    sql = sub.add_parser("sql", help="run a query (read from stdin when omitted or `-`)")
    sql.add_argument("query", nargs="?", default="-")
    return parser


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

    client = Client(resolve_profile(config, args.profile, args.url, args.user), timeout=args.timeout)
    if args.command == "ping":
        print(client.ping())
        return 0
    if args.command == "sql":
        query = sys.stdin.read() if args.query == "-" else args.query
        sys.stdout.write(client.query(query, output_format(args)))
        return 0
    raise AssertionError(args.command)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    except QueryError as e:
        print(e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
