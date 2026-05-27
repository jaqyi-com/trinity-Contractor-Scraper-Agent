# utils/address_normalizer.py
# Address normalization for dedup. Uses usaddress for parsing.

from typing import Optional

try:
    import usaddress
except ImportError:
    usaddress = None


def normalize_address(address: Optional[str]) -> Optional[str]:
    if not address:
        return None
    if usaddress is None:
        return address.strip().lower()
    try:
        parsed, _ = usaddress.tag(address)
        parts = []
        for key in ["AddressNumber", "StreetNamePreDirectional",
                    "StreetName", "StreetNamePostType",
                    "PlaceName", "StateName", "ZipCode"]:
            if key in parsed:
                parts.append(parsed[key])
        return " ".join(parts).lower()
    except Exception:
        return address.strip().lower()
