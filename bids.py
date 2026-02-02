# bids.py
import re

SUFFIXES = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}

def parse_amount(text: str) -> int:
    """
    Parse strings like: 250k, 2.5m, 1,000,000, 1K, 3B, 100000
    Returns integer amount or raises ValueError.
    """
    if not text or not isinstance(text, str):
        raise ValueError("Empty amount")
    t = text.strip().lower().replace(" ", "").replace(",", "")
    # plain digits
    if t.isdigit():
        return int(t)
    m = re.match(r"^([0-9]*\.?[0-9]+)([kmb])$", t)
    if m:
        num = float(m.group(1))
        suf = m.group(2)
        return int(num * SUFFIXES[suf])
    raise ValueError("Invalid format. Examples: 250k / 2.5m / 100000")

def fmt_amount(amount: int) -> str:
    """
    Format integer amount into short string (1K, 2.5M, 1B) with trimming.
    """
    if amount is None:
        return "0"
    amount = int(amount)
    if amount >= 1_000_000_000:
        v = amount / 1_000_000_000
        s = f"{v:.2f}B"
    elif amount >= 1_000_000:
        v = amount / 1_000_000
        s = f"{v:.2f}M"
    elif amount >= 1_000:
        v = amount / 1_000
        s = f"{v:.2f}K"
    else:
        return str(amount)
    return s.rstrip("0").rstrip(".")