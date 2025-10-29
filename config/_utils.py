"""
Shared utilities for configuration modules.
"""

from typing import Optional

def validate_timezone(name: str, value: str) -> None:
    """Validate that a timezone string is valid.

    Prefers Python 3.9+ zoneinfo validation and falls back to a small set of
    common timezone names if zoneinfo is unavailable.
    """
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        try:
            ZoneInfo(value)
        except Exception as exc:  # pragma: no cover - validation
            raise ValueError(f"{name} must be a valid IANA timezone, got: {value}") from exc
        return
    except Exception:
        # zoneinfo not available, fall back to common names
        pass

    common_timezones = {
        "UTC",
        "Etc/UTC",
        "GMT",
        "Europe/London",
        "US/Eastern",
        "US/Central",
        "US/Mountain",
        "US/Pacific",
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "Europe/Paris",
        "Europe/Berlin",
        "Asia/Tokyo",
        "Asia/Shanghai",
        "Asia/Hong_Kong",
        "Australia/Sydney",
    }
    if value not in common_timezones:
        raise ValueError(f"{name} must be a valid timezone string, got: {value}")



def _parse_excluded_hours(name: str, value: Optional[str]) -> list[int]:
    """Parse and validate a comma-separated list of hours to exclude from trading.

    Parameters:
        name: Environment variable name for error messages.
        value: Comma-separated hour values (e.g., "0,1,2,3,13,22") or None.

    Returns:
        List of validated hour integers (0-23). Returns an empty list if value is None or empty.

    Raises:
        ValueError: If parsing fails, hours are out of range, or duplicates are found.

    Examples:
        >>> _parse_excluded_hours("TEST", "0,1,2,3")
        [0, 1, 2, 3]
        >>> _parse_excluded_hours("TEST", "13, 22, 0")  # whitespace handled
        [13, 22, 0]
        >>> _parse_excluded_hours("TEST", None)
        []
        >>> _parse_excluded_hours("TEST", "")
        []
    """
    if value is None:
        return []

    raw = value.strip()
    if raw == "":
        return []

    hours: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if token == "":
            # Gracefully skip empty tokens (e.g., trailing commas)
            continue
        try:
            hour = int(token)
        except Exception as exc:
            raise ValueError(f"{name} must contain only integers, got: {token}") from exc
        if not (0 <= hour <= 23):
            raise ValueError(f"{name} hours must be between 0 and 23, got: {hour}")
        hours.append(hour)

    # Detect duplicates
    unique_hours = set(hours)
    if len(unique_hours) != len(hours):
        # Determine which values are duplicated while preserving predictable order in message
        seen: set[int] = set()
        duplicates: list[int] = []
        for h in hours:
            if h in seen and h not in duplicates:
                duplicates.append(h)
            seen.add(h)
        raise ValueError(f"{name} contains duplicate hours: {duplicates}")

    return hours