"""Rainfall metrics over complete Copenhagen calendar days.

The source schedule is fixed in UTC at 05:00, 11:00, 17:00 and 23:00.
Amounts belong to their timestamp's local date; they are not rates.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from math import isfinite
from zoneinfo import ZoneInfo

import pandas as pd


LOCAL_TIMEZONE = ZoneInfo("Europe/Copenhagen")
WET_DAY_THRESHOLD_MM = Decimal("20")


def expected_slots(start: date, end: date) -> pd.DatetimeIndex:
    """Return the complete UTC schedule for inclusive local calendar dates.

    Deriving the boundaries in local time handles DST and includes missing slots
    at either edge of the observed data, rather than shortening the first/last day.
    """
    if end < start:
        raise ValueError("Analysis end must not precede analysis start")
    start_utc = pd.Timestamp(datetime.combine(start, time.min, LOCAL_TIMEZONE)).tz_convert("UTC")
    end_utc = pd.Timestamp(
        datetime.combine(end + timedelta(days=1), time.min, LOCAL_TIMEZONE)
    ).tz_convert("UTC")
    anchor = start_utc.normalize() - timedelta(days=1) + timedelta(hours=23)
    slots = pd.date_range(anchor, end_utc, freq="6h", inclusive="left")
    return slots[(slots >= start_utc) & (slots < end_utc)]


def _exact_sum(values: list[Decimal]) -> Decimal:
    """Allow enough precision to add supplied finite values without rounding."""
    least_exponent = min(value.as_tuple().exponent for value in values)
    greatest_position = max(value.adjusted() for value in values)
    with localcontext() as context:
        context.prec = max(context.prec, greatest_position - least_exponent + len(str(len(values))) + 2)
        return sum(values, Decimal(0))


def _valid_amount(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount >= 0 else None


def daily_totals(observations: pd.DataFrame, start: date, end: date) -> pd.Series:
    """Return one Decimal or None for every local date in the analysis period.

    Call with one station's observations. A complete day has exactly one valid
    amount at every expected timestamp, with no additional timestamps. None
    means unknown, so incomplete days cannot silently become dry days.
    """
    required = {"station_id", "observed_at", "precip_mm"}
    if missing := required - set(observations.columns):
        raise ValueError(f"Missing observation columns: {', '.join(sorted(missing))}")
    if observations["station_id"].nunique(dropna=False) > 1:
        raise ValueError("Daily totals require observations for a single station")

    expected_by_date: dict[date, set[pd.Timestamp]] = defaultdict(set)
    for timestamp in expected_slots(start, end):
        expected_by_date[timestamp.tz_convert(LOCAL_TIMEZONE).date()].add(timestamp)

    actual_by_date: dict[date, list[tuple[pd.Timestamp, Decimal | None]]] = defaultdict(list)
    for row in observations.itertuples(index=False):
        timestamp = pd.Timestamp(row.observed_at)
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            raise ValueError("Observation timestamps must be valid and timezone-aware")
        timestamp = timestamp.tz_convert("UTC")
        local_date = timestamp.tz_convert(LOCAL_TIMEZONE).date()
        if start <= local_date <= end:
            actual_by_date[local_date].append((timestamp, _valid_amount(row.precip_mm)))

    totals: dict[date, Decimal | None] = {}
    for day in pd.date_range(start, end, freq="D").date:
        expected = expected_by_date[day]
        rows = actual_by_date[day]
        timestamps = {timestamp for timestamp, _ in rows}
        values = [value for _, value in rows if value is not None]
        complete = bool(expected) and timestamps == expected and len(rows) == len(expected) == len(values)
        totals[day] = _exact_sum(values) if complete else None
    return pd.Series(totals, dtype=object, name="precip_mm")


def three_day_totals(daily: pd.Series) -> list[tuple[date, Decimal]]:
    """Return (window start, amount) for three complete consecutive dates."""
    days = list(daily.items())
    windows = []
    for first, second, third in zip(days, days[1:], days[2:]):
        if second[0] != first[0] + timedelta(days=1) or third[0] != second[0] + timedelta(days=1):
            continue
        values = [first[1], second[1], third[1]]
        if all(value is not None for value in values):
            windows.append((first[0], _exact_sum(values)))
    return windows


def summarize_station(observations: pd.DataFrame, start: date, end: date) -> dict:
    """Calculate nullable metrics and coverage without counting unknown days."""
    daily = daily_totals(observations, start, end)
    complete_values = [value for value in daily if value is not None]
    windows = three_day_totals(daily)
    worst = float(max(amount for _, amount in windows)) if windows else None
    if worst is not None and not isfinite(worst):
        raise ValueError("Three-day rainfall exceeds the supported numeric range")
    return {
        "wet_day_count": sum(value >= WET_DAY_THRESHOLD_MM for value in complete_values) if complete_values else None,
        "worst_three_day_precip_mm": worst,
        "wet_day_status": "available" if complete_values else "no_complete_days",
        "three_day_status": "available" if windows else "no_complete_three_day_window",
        "coverage": {
            "complete_days": len(complete_values),
            "incomplete_days": len(daily) - len(complete_values),
            "eligible_three_day_windows": len(windows),
        },
    }
