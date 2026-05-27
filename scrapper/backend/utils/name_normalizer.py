# utils/name_normalizer.py
# Business name normalization for matching/dedup.

import re
from typing import Optional


SUFFIXES = {
    "llc", "inc", "incorporated", "corp", "corporation",
    "co", "company", "ltd", "limited", "plc", "lc",
}


def normalize_name(name: Optional[str]) -> str:
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r"[^\w\s]", " ", n)  # strip punctuation
    n = re.sub(r"\s+", " ", n).strip()
    tokens = [t for t in n.split() if t not in SUFFIXES]
    return " ".join(tokens)
