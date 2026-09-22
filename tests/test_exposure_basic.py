from datetime import date, timedelta
from decimal import Decimal

import pandas as pd

from app.exposure import daily_totals, summarize_station


def observations_for_days(amounts: list[list[str]]) -> pd.DataFrame:
    """Four UTC slots per winter local day; values are explicit hand fixtures."""
    rows = []
    first_timestamp = pd.Timestamp("2024-12-31T23:00:00Z")
    for day_number, day_amounts in enumerate(amounts):
        for slot_number, amount in enumerate(day_amounts):
            rows.append({
                "station_id": "S1",
                "observed_at": first_timestamp + timedelta(days=day_number, hours=slot_number * 6),
                "precip_mm": Decimal(amount),
            })
    return pd.DataFrame(rows)


def test_wet_threshold_is_inclusive_and_worst_window_is_hand_calculated():
    observations = observations_for_days([
        ["4.9", "5", "5", "5"],   # 19.9: dry
        ["5", "5", "5", "5"],     # 20: wet
        ["1", "2", "3", "4"],     # 10: dry
        ["5.1", "5", "5", "5"],   # 20.1: wet
    ])
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 4))
    assert list(daily_totals(observations, date(2025, 1, 1), date(2025, 1, 4))) == [
        Decimal("19.9"), Decimal("20"), Decimal("10"), Decimal("20.1")
    ]
    assert result == {
        "wet_day_count": 2,
        "worst_three_day_precip_mm": 50.1,  # max(19.9 + 20 + 10, 20 + 10 + 20.1)
        "wet_day_status": "available",
        "three_day_status": "available",
        "coverage": {"complete_days": 4, "incomplete_days": 0, "eligible_three_day_windows": 2},
    }


def test_three_day_window_cannot_bridge_a_missing_calendar_day():
    observations = observations_for_days([
        ["5", "5", "5", "5"],
        ["5", "5", "5", "5"],
        [],
        ["5", "5", "5", "5"],
    ])
    result = summarize_station(observations, date(2025, 1, 1), date(2025, 1, 4))
    assert result["wet_day_count"] == 3
    assert result["worst_three_day_precip_mm"] is None
    assert result["three_day_status"] == "no_complete_three_day_window"
    assert result["coverage"] == {
        "complete_days": 3, "incomplete_days": 1, "eligible_three_day_windows": 0,
    }
