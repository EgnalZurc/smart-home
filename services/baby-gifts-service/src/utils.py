"""Baby Gifts Service — Utility functions."""

import re


def parse_price(price_str: str) -> float:
    """Extract numeric value from price string for sorting.

    Args:
        price_str: Price string like "50€", "100-150€", "€€€"

    Returns:
        Numeric value for sorting. For ranges, returns the average.
        Returns 0 if no numeric value found.

    Examples:
        >>> parse_price("50€")
        50.0
        >>> parse_price("100-150€")
        125.0
        >>> parse_price("€€€")
        0
    """
    if not price_str:
        return 0

    # Remove currency symbols and spaces, find numbers
    numbers = re.findall(r"[\d,\.]+", price_str.replace(",", "."))
    if numbers:
        try:
            # If there's a range (e.g., "100-150"), use the average
            if len(numbers) >= 2:
                return (float(numbers[0]) + float(numbers[-1])) / 2
            return float(numbers[0])
        except ValueError:
            return 0
    return 0
