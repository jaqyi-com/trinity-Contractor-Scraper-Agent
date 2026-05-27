# utils/phone_normalizer.py
# Phone → E.164 format. Strip all non-digits, drop leading 1, prepend +1.

import re
from typing import Optional


def normalize_phone(phone: Optional[str]) -> Optional[str]:
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return None
    # Strip leading country code "1" if present
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"+1{digits}"
