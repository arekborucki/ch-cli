import pytest

from ch_cli import commands
from ch_cli.cli import main


def test_ident_rejects_injection():
    assert commands.ident("events_raw") == "`events_raw`"
    for bad in ("x; DROP TABLE y", "a`b", "1abc", "", "a.b"):
        with pytest.raises(ValueError):
            commands.ident(bad)


def test_table_ref():
    assert commands.table_ref("mercury.events_raw") == ("mercury", "events_raw")
    assert commands.table_ref("events_raw") == (None, "events_raw")
    with pytest.raises(ValueError):
        commands.table_ref("a.b.c")


@pytest.mark.parametrize(
    ("text", "sql"),
    [
        ("90s", "INTERVAL 90 SECOND"),
        ("30m", "INTERVAL 30 MINUTE"),
        ("1h", "INTERVAL 1 HOUR"),
        ("7d", "INTERVAL 7 DAY"),
    ],
)
def test_interval(text, sql):
    assert commands.interval(text) == sql


def test_interval_rejects_garbage():
    with pytest.raises(ValueError):
        commands.interval("1 hour")


def test_source_local_and_cluster():
    assert commands.source("replicas", None) == "system.replicas"
    assert commands.source("replicas", "mercury") == "clusterAllReplicas('mercury', system.replicas)"
    assert commands.source("disks", "mongodb-logs") == "clusterAllReplicas('mongodb-logs', system.disks)"
    with pytest.raises(ValueError):
        commands.source("replicas", "x', system.users) --")


def test_fresh_quotes_identifiers():
    sql = commands.fresh("mercury.events_raw", "received_at", "5m")
    assert "FROM `mercury`.`events_raw`" in sql
    assert "max(`received_at`)" in sql
    assert "INTERVAL 5 MINUTE" in sql
    assert "WHERE `received_at` > now() - INTERVAL 1 DAY" in sql
    assert "INTERVAL 2 HOUR" in commands.fresh("t", "ts", lookback="2h")


def test_fields_uses_given_database():
    assert "database = 'mercury' AND table = 'events_raw'" in commands.fields("mercury.events_raw")
    assert "database = currentDatabase()" in commands.fields("events_raw")


def test_filters_and_limits():
    assert "NOT IN ('system'" in commands.tables()
    assert "t.database = 'mercury'" in commands.tables("mercury")
    assert "WHERE NOT is_done" in commands.mutations()
    assert "WHERE NOT is_done" not in commands.mutations(include_done=True)
    assert "absolute_delay > 60" in commands.replicas(problems_only=True)
    assert "absolute_delay > 5" in commands.replicas(problems_only=True, min_delay=5)
    assert "query_duration_ms >= 5000" in commands.slow(min_ms=5000)


@pytest.mark.parametrize(
    "argv",
    [
        ["health"],
        ["tables", "-d", "mercury"],
        ["fields", "mercury.events_raw"],
        ["disk", "-c", "mercury"],
        ["fresh", "mercury.events_raw", "--ts", "received_at"],
        ["replicas", "--problems"],
        ["mutations", "--all"],
        ["merges"],
        ["slow", "--since", "24h"],
        ["backups"],
        ["backups", "--actions"],
    ],
)
def test_print_sql_needs_no_server(argv, capsys, monkeypatch):
    monkeypatch.setenv("CH_CLI_CONFIG", "/nonexistent")
    assert main(["--print-sql", *argv]) == 0
    assert capsys.readouterr().out.lstrip().startswith("SELECT")


def test_bad_identifier_exit_code(capsys, monkeypatch):
    monkeypatch.setenv("CH_CLI_CONFIG", "/nonexistent")
    assert main(["--print-sql", "fresh", "x;drop", "--ts", "t"]) == 2
    assert "invalid identifier" in capsys.readouterr().err


def test_backups_sql():
    assert "FROM system.backup_list" in commands.backups()
    assert "if(required = '', 'full', 'increment')" in commands.backups()
    actions = commands.backup_actions(5)
    assert "FROM system.backup_actions" in actions and "command != 'list'" in actions and "LIMIT 5" in actions
