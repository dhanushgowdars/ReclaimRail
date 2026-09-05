"""Human-readable money formatting at API presentation boundaries."""


def format_minor_amount(amount_minor: int, currency: str) -> str:
    """Format stored minor units without changing the underlying value."""
    major, remainder = divmod(amount_minor, 100)
    number = f"{major:,}" + (f".{remainder:02d}" if remainder else "")
    return f"₹{number}" if currency.upper() == "INR" else f"{number} {currency.upper()}"
