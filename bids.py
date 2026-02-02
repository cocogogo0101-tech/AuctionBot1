# bids.py
"""
Bid amount parsing and formatting utilities.
Handles conversion between human-readable formats (250k, 2.5m) and integers.
Includes validation and error handling for bid amounts.
"""

import re
from typing import Union, Tuple
from config import MIN_BID_AMOUNT, MAX_BID_AMOUNT

# Suffix multipliers
SUFFIXES = {
    "k": 1_000,
    "m": 1_000_000,
    "b": 1_000_000_000,
    "t": 1_000_000_000_000,
}

class BidParseError(Exception):
    """Custom exception for bid parsing errors."""
    pass

class BidValidationError(Exception):
    """Custom exception for bid validation errors."""
    pass


def parse_amount(text: str, strict: bool = True) -> int:
    """
    Parse strings like: 250k, 2.5m, 1,000,000, 1K, 3B, 100000
    
    Args:
        text: Input string to parse
        strict: If True, raises exception on invalid input. If False, returns 0.
    
    Returns:
        Integer amount
        
    Raises:
        BidParseError: If parsing fails and strict=True
        
    Examples:
        >>> parse_amount("250k")
        250000
        >>> parse_amount("2.5m")
        2500000
        >>> parse_amount("1,000,000")
        1000000
    """
    if not text or not isinstance(text, str):
        if strict:
            raise BidParseError("Empty or invalid amount")
        return 0
    
    # Clean the input
    original = text
    text = text.strip().lower()
    
    # Remove spaces and common separators
    text = text.replace(" ", "").replace(",", "").replace("_", "")
    
    # Handle plain digits
    if text.isdigit():
        try:
            amount = int(text)
            return amount
        except ValueError:
            if strict:
                raise BidParseError(f"Invalid number format: {original}")
            return 0
    
    # Handle suffix format (e.g., 250k, 2.5m)
    pattern = r"^([0-9]*\.?[0-9]+)([kmbt])$"
    match = re.match(pattern, text)
    
    if match:
        try:
            num = float(match.group(1))
            suffix = match.group(2)
            amount = int(num * SUFFIXES[suffix])
            return amount
        except (ValueError, KeyError):
            if strict:
                raise BidParseError(f"Invalid format: {original}")
            return 0
    
    # If we get here, format is invalid
    if strict:
        raise BidParseError(
            f"Invalid format: {original}. "
            "Examples: 250k, 2.5m, 1000000, 5b"
        )
    return 0


def validate_amount(amount: int, min_amount: int = MIN_BID_AMOUNT, 
                    max_amount: int = MAX_BID_AMOUNT) -> Tuple[bool, str]:
    """
    Validate that a bid amount is within acceptable range.
    
    Args:
        amount: Amount to validate
        min_amount: Minimum allowed amount
        max_amount: Maximum allowed amount
        
    Returns:
        Tuple of (is_valid, error_message)
        
    Examples:
        >>> validate_amount(250000)
        (True, "")
        >>> validate_amount(500)
        (False, "Amount must be at least 1K")
    """
    if amount < min_amount:
        return False, f"Amount must be at least {fmt_amount(min_amount)}"
    
    if amount > max_amount:
        return False, f"Amount cannot exceed {fmt_amount(max_amount)}"
    
    return True, ""


def fmt_amount(amount: Union[int, float, None], fallback: str = "0") -> str:
    """
    Format integer amount into short string (1K, 2.5M, 1B) with trimming.
    
    Args:
        amount: Amount to format (can be None)
        fallback: String to return if amount is None or 0
        
    Returns:
        Formatted string
        
    Examples:
        >>> fmt_amount(250000)
        '250K'
        >>> fmt_amount(2500000)
        '2.5M'
        >>> fmt_amount(1500000000)
        '1.5B'
        >>> fmt_amount(None)
        '0'
    """
    if amount is None or amount == 0:
        return fallback
    
    try:
        amount = int(amount)
    except (ValueError, TypeError):
        return fallback
    
    # Handle negative amounts
    negative = amount < 0
    amount = abs(amount)
    
    # Determine the appropriate suffix
    if amount >= 1_000_000_000_000:
        value = amount / 1_000_000_000_000
        suffix = "T"
    elif amount >= 1_000_000_000:
        value = amount / 1_000_000_000
        suffix = "B"
    elif amount >= 1_000_000:
        value = amount / 1_000_000
        suffix = "M"
    elif amount >= 1_000:
        value = amount / 1_000
        suffix = "K"
    else:
        return ("-" if negative else "") + str(amount)
    
    # Format with 2 decimal places, then strip trailing zeros
    formatted = f"{value:.2f}{suffix}"
    formatted = formatted.rstrip("0").rstrip(".")
    
    return ("-" if negative else "") + formatted


def parse_and_validate(text: str, min_amount: int = MIN_BID_AMOUNT,
                       max_amount: int = MAX_BID_AMOUNT) -> Tuple[int, str]:
    """
    Parse and validate amount in one step.
    
    Args:
        text: Input string to parse
        min_amount: Minimum allowed amount
        max_amount: Maximum allowed amount
        
    Returns:
        Tuple of (amount, error_message)
        If error_message is empty, amount is valid.
        If error_message is not empty, amount is 0.
        
    Examples:
        >>> parse_and_validate("250k")
        (250000, "")
        >>> parse_and_validate("500")
        (0, "Amount must be at least 1K")
    """
    try:
        amount = parse_amount(text, strict=True)
    except BidParseError as e:
        return 0, str(e)
    
    is_valid, error = validate_amount(amount, min_amount, max_amount)
    if not is_valid:
        return 0, error
    
    return amount, ""


def compare_amounts(amount1: int, amount2: int) -> str:
    """
    Compare two amounts and return a human-readable difference.
    
    Args:
        amount1: First amount
        amount2: Second amount
        
    Returns:
        Formatted string showing the difference
        
    Examples:
        >>> compare_amounts(300000, 250000)
        '+50K'
        >>> compare_amounts(250000, 300000)
        '-50K'
    """
    diff = amount1 - amount2
    if diff == 0:
        return "±0"
    prefix = "+" if diff > 0 else ""
    return prefix + fmt_amount(diff)


def calculate_commission(amount: int, commission_percent: int) -> int:
    """
    Calculate commission amount.
    
    Args:
        amount: Base amount
        commission_percent: Commission percentage (e.g., 20 for 20%)
        
    Returns:
        Commission amount as integer
        
    Examples:
        >>> calculate_commission(1000000, 20)
        200000
    """
    if amount <= 0 or commission_percent <= 0:
        return 0
    return int((amount * commission_percent) / 100)


# ==================== TESTING ====================
if __name__ == "__main__":
    # Quick self-test
    test_cases = [
        ("250k", 250_000),
        ("2.5m", 2_500_000),
        ("1,000,000", 1_000_000),
        ("5b", 5_000_000_000),
        ("100", 100),
        ("1.5K", 1_500),
    ]
    
    print("Testing parse_amount():")
    for input_str, expected in test_cases:
        try:
            result = parse_amount(input_str)
            status = "✓" if result == expected else "✗"
            print(f"{status} {input_str} -> {result} (expected {expected})")
        except Exception as e:
            print(f"✗ {input_str} -> Error: {e}")
    
    print("\nTesting fmt_amount():")
    test_amounts = [250_000, 2_500_000, 1_500_000_000, 100, None]
    for amt in test_amounts:
        print(f"{amt} -> {fmt_amount(amt)}")
