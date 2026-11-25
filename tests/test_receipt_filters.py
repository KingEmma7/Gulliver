import json

import pytest

from gulliver import core
from gulliver.cli import main
from gulliver.store import Store


@pytest.fixture
def receipts(settings):
    store = Store(settings.state_dir)
    records = [
        ("old-run", "run", "ok", "warehouse"),
        ("other-connection", "run", "ok", "local"),
        ("other-status", "run", "block", "warehouse"),
        ("new-run", "run", "ok", "warehouse"),
        ("newest-preflight", "preflight", "ok", "warehouse"),
    ]
    for i, (receipt_id, action, status, connection) in enumerate(records):
        store.save_receipt({
            "receipt_id": f"gv-20260101-00000{i}-{receipt_id}", "action": action,
            "status": status, "connection": connection,
            "created_at": f"2026-01-01T00:00:0{i}+00:00", "sql": "select 1", "preview": [{"private": "row"}],
        })
    return settings


@pytest.mark.parametrize("filters, expected", [
    ({"action": "run"}, ["new-run", "other-status", "other-connection", "old-run"]),
    ({"connection": "local"}, ["other-connection"]),
    ({"action": "run", "connection": "warehouse", "status": "ok"}, ["new-run", "old-run"]),
    ({"action": "missing"}, []),
    ({"connection": "missing"}, []),
])
def test_receipt_filters_combine_and_preserve_summary_only(receipts, capsys, filters, expected):
    result = core.list_receipts(receipts, **filters)
    assert result["status"] == "ok"
    assert [rec["receipt_id"].split("-", 3)[3] for rec in result["receipts"]] == expected
    assert all("preview" not in rec for rec in result["receipts"])
    args = ["receipt", "--list", "--json"]
    for key, value in filters.items():
        args.extend([f"--{key}", value])
    assert main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert [rec["receipt_id"].split("-", 3)[3] for rec in result["receipts"]] == expected


def test_receipt_limit_is_applied_after_all_filters(receipts, capsys):
    filters = {"action": "run", "connection": "warehouse", "status": "ok"}
    result = core.list_receipts(receipts, limit=1, **filters)
    assert [rec["receipt_id"].split("-", 3)[3] for rec in result["receipts"]] == ["new-run"]
    assert main(["receipt", "--list", "--action", "run", "--connection", "warehouse",
                 "--status", "ok", "--limit", "1"]) == 0
    output = capsys.readouterr().out
    assert "new-run" in output
    assert "old-run" not in output
    assert "preflight" not in output


@pytest.mark.parametrize("filters, message", [
    ({"status": "missing"}, "No receipts match --status 'missing'."),
    ({"action": "missing"}, "No receipts match --action 'missing'."),
    ({"connection": "missing"}, "No receipts match --connection 'missing'."),
    ({"action": "missing", "connection": "warehouse"},
     "No receipts match --action 'missing', --connection 'warehouse'."),
    ({"status": "block", "action": "preflight", "connection": "local"},
     "No receipts match --status 'block', --action 'preflight', --connection 'local'."),
    ({"action": ""}, "No receipts match --action ''."),
])
def test_empty_filtered_receipts_name_only_active_filters(receipts, capsys, filters, message):
    result = core.list_receipts(receipts, **filters)
    assert result["receipts"] == []
    assert result["message"] == message
    args = ["receipt", "--list"]
    for key, value in filters.items():
        args.extend([f"--{key}", value])
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines()[0] == message
    assert main([*args, "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["receipts"] == []
    assert output["message"] == message


def test_empty_store_with_active_filter_names_it(settings):
    result = core.list_receipts(settings, action="missing")
    assert result["receipts"] == []
    assert result["message"] == "No receipts match --action 'missing'."


def test_matching_filter_keeps_receipt_output(receipts, capsys):
    result = core.list_receipts(receipts, connection="local")
    assert "message" not in result
    assert [rec["receipt_id"].split("-", 3)[3] for rec in result["receipts"]] == ["other-connection"]
    assert main(["receipt", "--list", "--connection", "local"]) == 0
    output = capsys.readouterr().out
    assert "other-connection" in output
    assert "No receipts" not in output


@pytest.mark.parametrize("filters, expected_next_step", [
    ({"status": "missing"}, "Statuses in your receipts: block, ok."),
    ({"action": "missing"}, "Actions in your receipts: preflight, run."),
    ({"connection": "missing"}, "Connections in your receipts: local, warehouse."),
    (
        {"action": "missing", "connection": "warehouse"},
        "Actions in your receipts: preflight, run. Connections in your receipts: local, warehouse.",
    ),
    (
        {"status": "block", "action": "preflight", "connection": "local"},
        "Statuses in your receipts: block, ok. Actions in your receipts: preflight, run. "
        "Connections in your receipts: local, warehouse.",
    ),
])
def test_empty_filtered_receipts_next_step_lists_active_filter_values(
    receipts, capsys, filters, expected_next_step
):
    result = core.list_receipts(receipts, **filters)
    assert result["receipts"] == []
    assert result["next_step"] == expected_next_step
    args = ["receipt", "--list", "--json"]
    for key, value in filters.items():
        args.extend([f"--{key}", value])
    assert main(args) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["next_step"] == expected_next_step


def test_empty_store_filtered_receipts_next_step_says_none(settings, capsys):
    result = core.list_receipts(settings, action="missing", connection="missing")
    assert result["next_step"] == "Actions in your receipts: none. Connections in your receipts: none."
    assert main(["receipt", "--list", "--action", "missing", "--connection", "missing", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["next_step"] == "Actions in your receipts: none. Connections in your receipts: none."
