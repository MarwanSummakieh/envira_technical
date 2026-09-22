from datetime import date, timedelta
from decimal import Decimal
import json

import pandas as pd
import pytest

from app.exposure import daily_totals, expected_slots, summarize_station, three_day_totals


def winter_observations(day_amounts: list[list[object]]) -> pd.DataFrame:
    rows = []
    for day_number, amounts in enumerate(day_amounts):
        for slot_number, amount in enumerate(amounts):
            rows.append({
                "station_id": "S1",
                "observed_at": pd.Timestamp("2024-12-31T23:00:00Z")
                + timedelta(days=day_number, hours=6 * slot_number),
                "precip_mm": amount,
            })
    return pd.DataFrame(rows, columns=["station_id", "observed_at", "precip_mm"])


def test_late_utc_observation_belongs_to_the_following_local_date():
    observations = winter_observations([[Decimal("8"), Decimal("4"), Decimal("4"), Decimal("4")]])
    # Eight millimetres recorded on December 31 UTC belong to January 1 locally.
    totals = daily_totals(observations, date(2024, 12, 31), date(2025, 1, 1))
    assert totals.to_dict() == {date(2024, 12, 31): None, date(2025, 1, 1): Decimal("20")}


@pytest.mark.parametrize("day, utc_times, local_hours", [
    (
        date(2025, 3, 30),
        ["2025-03-29T23:00:00Z", "2025-03-30T05:00:00Z", "2025-03-30T11:00:00Z", "2025-03-30T17:00:00Z"],
        [0, 7, 13, 19],
    ),
    (
        date(2025, 10, 26),
        ["2025-10-25T23:00:00Z", "2025-10-26T05:00:00Z", "2025-10-26T11:00:00Z", "2025-10-26T17:00:00Z"],
        [1, 6, 12, 18],
    ),
    (
        date(2026, 3, 29),
        ["2026-03-28T23:00:00Z", "2026-03-29T05:00:00Z", "2026-03-29T11:00:00Z", "2026-03-29T17:00:00Z"],
        [0, 7, 13, 19],
    ),
])
def test_dst_calendar_day_uses_hand_known_utc_slots(day, utc_times, local_hours):
    timestamps = pd.DatetimeIndex(utc_times)
    assert list(expected_slots(day, day)) == list(timestamps)
    assert list(timestamps.tz_convert("Europe/Copenhagen").hour) == local_hours
    observations = pd.DataFrame({
        "station_id": ["S1"] * 4,
        "observed_at": timestamps,
        "precip_mm": [Decimal("2"), Decimal("3"), Decimal("5"), Decimal("10")],
    })
    result = summarize_station(observations, day, day)
    assert result["wet_day_count"] == 1
    assert result["coverage"] == {
        "complete_days": 1, "incomplete_days": 0, "eligible_three_day_windows": 0,
    }


def test_missing_slots_and_entire_missing_days_remain_unknown():
    observations = winter_observations([
        ["5", "5", "5", "5"],
        ["5", "5", "5"],  # An observed partial total must not become a dry day.
        [],
        ["6", "6", "6", "6"],
    ])
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 4))
    assert result["wet_day_count"] == 2
    assert result["worst_three_day_precip_mm"] is None
    assert result["coverage"] == {
        "complete_days": 2, "incomplete_days": 2, "eligible_three_day_windows": 0,
    }


@pytest.mark.parametrize("invalid", [
    None, "", "not-a-number", Decimal("-1"), Decimal("-999"), Decimal("-9999"),
    Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity"), float("nan"), float("inf"),
])
def test_invalid_amount_makes_whole_day_unknown_and_json_remains_finite(invalid):
    observations = winter_observations([["10", "10", "10", invalid]])
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 1))
    assert result == {
        "wet_day_count": None,
        "worst_three_day_precip_mm": None,
        "wet_day_status": "no_complete_days",
        "three_day_status": "no_complete_three_day_window",
        "coverage": {"complete_days": 0, "incomplete_days": 1, "eligible_three_day_windows": 0},
    }
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_wet_threshold_uses_exact_decimal_totals_below_at_and_above_twenty():
    observations = winter_observations([
        ["4.99999999999999999999999999999"] * 4,
        ["0.1", "0.2", "0.3", "19.4"],
        ["20", "0.0000000000000000000000000001", "0", "0"],
    ])
    totals = daily_totals(observations, date(2025, 1, 1), date(2025, 1, 3))
    assert list(totals) == [
        Decimal("19.99999999999999999999999999996"),
        Decimal("20.0"),
        Decimal("20.0000000000000000000000000001"),
    ]
    assert summarize_station(observations, date(2025, 1, 1), date(2025, 1, 3))["wet_day_count"] == 2


def test_no_observations_preserves_the_global_period_and_null_metrics():
    result = summarize_station(winter_observations([]), date(2025, 1, 1), date(2025, 1, 5))
    assert result["wet_day_count"] is None
    assert result["wet_day_status"] == "no_complete_days"
    assert result["worst_three_day_precip_mm"] is None
    assert result["coverage"] == {
        "complete_days": 0, "incomplete_days": 5, "eligible_three_day_windows": 0,
    }


def test_complete_zero_days_are_available_but_two_days_cannot_form_a_window():
    observations = winter_observations([["0", "0", "0", "0"], ["0", "0", "0", "0"]])
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 2))
    assert result["wet_day_count"] == 0
    assert result["wet_day_status"] == "available"
    assert result["worst_three_day_precip_mm"] is None
    assert result["three_day_status"] == "no_complete_three_day_window"
    assert result["coverage"]["eligible_three_day_windows"] == 0


def test_three_complete_dry_days_return_an_available_zero_total():
    observations = winter_observations([["0", "0", "0", "0"]] * 3)
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 3))
    assert result["wet_day_count"] == 0
    assert result["worst_three_day_precip_mm"] == 0.0
    assert result["three_day_status"] == "available"
    assert result["coverage"]["eligible_three_day_windows"] == 1


def test_missing_day_does_not_bridge_high_totals_into_a_false_rolling_maximum():
    observations = winter_observations([
        ["25", "25", "25", "25"],
        [],
        ["5", "5", "5", "5"],
        ["5", "5", "5", "5"],
        ["5", "5", "5", "5"],
    ])
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 5))
    assert result["worst_three_day_precip_mm"] == 60.0
    assert result["coverage"]["eligible_three_day_windows"] == 1
    # The window helper also rejects date gaps if called without a full date index.
    gapped = pd.Series({
        date(2025, 1, 1): Decimal("100"),
        date(2025, 1, 3): Decimal("20"),
        date(2025, 1, 4): Decimal("20"),
    }, dtype=object)
    assert three_day_totals(gapped) == []


@pytest.mark.parametrize("extra_timestamp", ["2024-12-31T23:00:00Z", "2025-01-01T00:00:00Z"])
def test_duplicate_or_off_schedule_extra_cannot_make_a_day_complete(extra_timestamp):
    observations = winter_observations([["5", "5", "5", "5"]])
    extra = pd.DataFrame([{
        "station_id": "S1", "observed_at": pd.Timestamp(extra_timestamp), "precip_mm": Decimal("5"),
    }])
    result = summarize_station(pd.concat([observations, extra]), date(2025, 1, 1), date(2025, 1, 1))
    assert result["coverage"]["complete_days"] == 0
    assert result["wet_day_count"] is None


def test_missing_first_and_last_slots_are_not_trimmed_from_day_expectations():
    observations = winter_observations([
        ["5", "5", "5", "5"],
        ["5", "5", "5", "5"],
        ["5", "5", "5", "5"],
    ]).iloc[1:-1]
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 3))
    assert result["coverage"] == {
        "complete_days": 1, "incomplete_days": 2, "eligible_three_day_windows": 0,
    }
    assert result["wet_day_count"] == 1


def test_unrepresentable_three_day_total_is_rejected_before_json_serialization():
    observations = winter_observations([[Decimal("1e308")] * 4] * 3)
    with pytest.raises(ValueError, match="supported numeric range"):
        summarize_station(observations, date(2025, 1, 1), date(2025, 1, 3))
