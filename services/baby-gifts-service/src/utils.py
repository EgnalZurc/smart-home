"""Baby Gifts Service — Utility functions.

Helper functions for data processing and formatting used across the service.
"""

import re
from typing import Final

# Regex pattern to extract numeric values from price strings.
# Matches digits with optional decimal separators (comma or period).
_PRICE_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\d,\.]+")


def parse_price(price_str: str) -> float:
    """Extract numeric value from price string for sorting.

    Parses various price formats and returns a sortable numeric value.
    For price ranges, returns the midpoint. For symbolic prices (e.g., "€€€"),
    returns 0 since no numeric value is available.

    Args:
        price_str: Price string in various formats:
            - Simple: "50€", "€50", "50 EUR"
            - Range: "100-150€", "100€ - 150€"
            - Symbolic: "€€€", "€€"
            - Empty or None-like values

    Returns:
        Numeric value suitable for sorting:
        - Single price: the price as float
        - Range: average of min and max
        - No numeric content: 0.0

    Raises:
        This function does not raise exceptions. Invalid or unparseable
        input returns 0.0 instead of raising ValueError, making it safe
        for use in sorting operations where a fallback is preferable.

    Examples:
        >>> parse_price("50€")
        50.0
        >>> parse_price("100-150€")
        125.0
        >>> parse_price("€€€")
        0.0
        >>> parse_price("")
        0.0
    """
    if not price_str:
        return 0.0

    # Normalize decimal separator (European format uses comma)
    normalized: str = price_str.replace(",", ".")

    # Extract all numeric values from the string
    numbers: list[str] = _PRICE_NUMBER_PATTERN.findall(normalized)

    if not numbers:
        return 0.0

    try:
        # If multiple numbers found (likely a range), use average of first and last
        if len(numbers) >= 2:
            min_price: float = float(numbers[0])
            max_price: float = float(numbers[-1])
            return (min_price + max_price) / 2.0
        return float(numbers[0])
    except ValueError:
        # Malformed number string (e.g., multiple decimal points)
        return 0.0
