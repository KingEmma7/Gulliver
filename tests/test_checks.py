import pytest

from gulliver.checks import parse_spec
from gulliver.features import check


def _bounds(text):
    return parse_spec(ranges=[f"amount={text}"]).ranges["amount"]

@pytest.mark.parametrize("value", [-1, -5])
def test_min_rows_refuses_negative(value):
    with pytest.raises(ValueError, match=r"min_rows needs 0 or more"):
        parse_spec(min_rows=value)

@pytest.mark.parametrize("value", [-5.0, float("nan"), float("inf"), float("-inf")])
def test_max_change_refuses_negative_or_non_finite(value):
    with pytest.raises(ValueError, match=r"max_change needs a finite number"):
        parse_spec(max_change_pct=value)



@pytest.mark.parametrize("text", ["nan:", ":inf", "-inf:", ":nan"])
def test_range_refuses_non_finite_bounds(text):
    with pytest.raises(ValueError, match="finite"):
        parse_spec(ranges=[f"amount={text}"])

def test_zero_thresholds_still_parse():
    spec = parse_spec(min_rows=0, max_change_pct=0.0)
    assert spec.min_rows == 0
    assert spec.max_change_pct == 0.0

def test_range_refuses_a_non_number():
    with pytest.raises(ValueError, match=r"range for 'amount' needs numbers, got 'abc'"):
        parse_spec(ranges=["amount=abc:1"])


def test_range_refuses_inverted_bounds():
    with pytest.raises(ValueError, match=r"range for 'amount' has min 100 > max 1"):
        parse_spec(ranges=["amount=100:1"])


def test_range_bounds_still_parse():
    assert _bounds("0:") == (0.0, None)
    assert _bounds(":10") == (None, 10.0)
    assert _bounds("5:5") == (5.0, 5.0)


def test_merge_specs():
    from gulliver.checks import CheckSpec, merge_specs

    base = CheckSpec(
        unique=[["id"]],
        not_null=["user_id"],
        accepted={"status": ["active"]},
        ranges={"amount": (0.0, 100.0)},
        fresh={"ts": "24h"},
        min_rows=100,
        max_change_pct=10.0,
    )
    override = CheckSpec(
        unique=[["id"], ["email", "domain"]],
        not_null=["user_id", "email"],
        accepted={"status": ["active", "pending"], "type": ["a", "b"]},
        ranges={"amount": (10.0, 50.0), "score": (0.0, 1.0)},
        fresh={"ts": "12h", "created_at": "1h"},
        min_rows=500,
        max_change_pct=5.0,
    )
    merged = merge_specs(base, override)
    assert merged.unique == [["id"], ["email", "domain"]]
    assert merged.not_null == ["user_id", "email"]
    assert merged.accepted == {"status": ["active", "pending"], "type": ["a", "b"]}
    assert merged.ranges == {"amount": (10.0, 50.0), "score": (0.0, 1.0)}
    assert merged.fresh == {"ts": "12h", "created_at": "1h"}
    assert merged.min_rows == 500
    assert merged.max_change_pct == 5.0

    # Merging with empty override preserves base values
    empty_override = CheckSpec()
    merged_preserve = merge_specs(base, empty_override)
    assert merged_preserve.unique == [["id"]]
    assert merged_preserve.not_null == ["user_id"]
    assert merged_preserve.min_rows == 100
    assert merged_preserve.max_change_pct == 10.0


def test_empty_check_records_history_without_claiming_validation(settings):
    result = check(settings, "users")
    assert result["status"] == "ok"
    assert result.get("checks_requested") == 0
    assert "No checks were requested" in result["next_step"]
    assert "row count was recorded" in result["next_step"]
    assert "--unique" in result["next_step"]
    assert "All checks passed" not in result["next_step"]
    following = check(settings, "users", max_change_pct=0)
    row_count = next(item for item in following["checks"] if item["check"] == "row_count")
    assert row_count["previous_rows"] == row_count["rows"]


def test_requested_checks_keep_the_existing_result(settings):
    for options in ({"unique": ["user_id"]}, {"min_rows": 0}):
        result = check(settings, "users", **options)
        assert result["status"] == "ok"
        assert result["next_step"] == "All checks passed."
        assert "checks_requested" not in result


# -- max_null: a column that may be partly empty, but not too much -------------------------
@pytest.mark.parametrize("text, message", [
    ("col=nan", "finite"),
    ("col=inf", "finite"),
    ("col=-1", "between 0 and 100"),
    ("col=101", "between 0 and 100"),
    ("col=abc", "needs a percentage"),
    ("col", "needs col=PCT"),
])
def test_max_null_refuses_bad_values(text, message):
    with pytest.raises(ValueError, match=message):
        parse_spec(max_null=[text])


def test_max_null_accepts_the_bounds():
    assert parse_spec(max_null=["col=0"]).max_null == {"col": 0.0}
    assert parse_spec(max_null=["col=100"]).max_null == {"col": 100.0}
    assert parse_spec(max_null=["col=2.5", "other=0"]).max_null == {"col": 2.5, "other": 0.0}


def test_max_null_counts_as_a_requested_check():
    assert not parse_spec(max_null=["col=5"]).is_empty()


# -- max_null in gulliver.toml ------------------------------------------------------------
def test_max_null_in_a_configured_check():
    from gulliver.checks import parse_check_config

    cfg = parse_check_config("events", {"target": "events", "max_null": {"amount": 5}})
    assert cfg.spec.max_null == {"amount": 5.0}

    cfg = parse_check_config("events", {"target": "events", "max_null": ["amount=2.5", "email=0"]})
    assert cfg.spec.max_null == {"amount": 2.5, "email": 0.0}


@pytest.mark.parametrize("data, message", [
    ({"max_null": {"amount": 101}}, "between 0 and 100"),
    ({"max_null": {"amount": "five"}}, "must be a number"),
    ({"max_null": ["amount=nan"]}, "finite"),
    ({"max_null": ["amount"]}, "col=PCT"),
])
def test_max_null_in_a_configured_check_refuses_bad_values(data, message):
    from gulliver.checks import parse_check_config
    from gulliver.config import ConfigError

    with pytest.raises(ConfigError, match=message):
        parse_check_config("events", {"target": "events", **data})
