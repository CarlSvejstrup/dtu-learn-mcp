import pytest

from dtulearn import __version__, cli


@pytest.mark.parametrize("argv, expected", [
    (["setup", "-y", "--no-clients", "--no-schedule"], dict(cmd="setup", yes=True, no_clients=True, no_schedule=True)),
    (["login", "--timeout", "60"], dict(cmd="login", timeout=60)),
    (["login"], dict(cmd="login", timeout=300)),
    (["status", "--json", "--offline"], dict(cmd="status", json=True, offline=True)),
    (["doctor"], dict(cmd="doctor")),
    (["connect"], dict(cmd="connect", app=None, force=False)),
    (["connect", "cursor", "--force"], dict(cmd="connect", app="cursor", force=True)),
    (["courses", "--all-types", "--current"], dict(cmd="courses", all_types=True, current=True)),
    (["scrape", "--course", "338557", "340001", "--sync", "--dry-run", "--no-linked", "--force"],
     dict(cmd="scrape", course=[338557, 340001], sync=True, dry_run=True, no_linked=True, force=True, current=False)),
    (["scrape", "--all", "--include-inactive", "--no-vault"], dict(cmd="scrape", all=True, include_inactive=True, no_vault=True)),
    (["sync", "--dry-run", "--no-vault", "--config", "/x/sync.json", "--out", "/x/out"],
     dict(cmd="sync", dry_run=True, no_vault=True, config="/x/sync.json", out="/x/out")),
    (["schedule", "install", "--hour", "8"], dict(cmd="schedule", action="install", hour=8)),
    (["schedule", "status"], dict(cmd="schedule", action="status", hour=7)),
    (["auto", "--now"], dict(cmd="auto", now=True)),
    (["mcp"], dict(cmd="mcp")),
])
def test_build_parser_subcommands(argv, expected):
    ns = vars(cli.build_parser().parse_args(argv))
    assert {k: ns[k] for k in expected} == expected


def test_scrape_defaults_point_at_data_home(dl):
    ns = cli.build_parser().parse_args(["scrape", "--current"])
    assert ns.out == str(dl.paths.OUT) and ns.config == str(dl.paths.SYNC_CONFIG)
    assert ns.sync is False and ns.course is None


@pytest.mark.parametrize("argv", [[], ["nope"], ["schedule", "restart"], ["connect", "vscode"], ["scrape", "--course"]])
def test_build_parser_rejects(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.build_parser().parse_args(argv)
    assert e.value.code == 2


def test_scrape_needs_a_selection(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["scrape"])
    assert e.value.code == 2
    assert "scrape needs --current, --course ID... or --all" in capsys.readouterr().err


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert capsys.readouterr().out.strip() == f"dtu-learn {__version__}"


def test_setup_yes_keeps_optional_schedule_off():
    from dtulearn import wizard
    assert wizard._ask("Connect Claude Code?", True, assume_yes=True) is True
    assert wizard._ask("Refresh automatically every morning?", False, assume_yes=True) is False
