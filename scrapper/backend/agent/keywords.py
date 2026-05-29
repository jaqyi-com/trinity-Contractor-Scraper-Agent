# keywords.py
# DB-backed keyword store + CRUD with change-log tracking.
# All storage is via agent/db.py (Google Sheets backend).

from typing import Any, Dict, List, Optional

from agent import db


def list_keywords(tier: Optional[str] = None) -> List[Dict[str, Any]]:
    return db.list_keywords(tier)


def create_keyword(
    tier: str,
    keyword: str,
    notes: Optional[str] = None,
    created_by: str = "user",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert + log. Returns {} if (tier, keyword) already exists."""
    created = db.insert_keyword_raw(tier, keyword, notes, created_by)
    if not created:
        return {}
    db.insert_keyword_change({
        "keyword_id": created["id"],
        "action": "CREATE",
        "tier": tier,
        "keyword": keyword.lower(),
        "after_data": {
            "tier": tier, "keyword": keyword.lower(), "active": True, "notes": notes,
        },
        "changed_by": created_by,
        "reason": reason,
    })
    return {
        "id": created["id"],
        "tier": created["tier"],
        "keyword": created["keyword"],
        "active": created["active"],
        "notes": created.get("notes"),
        "created_by": created.get("created_by"),
    }


def update_keyword(
    keyword_id: int,
    updates: Dict[str, Any],
    changed_by: str = "user",
    reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    if not updates:
        return None
    allowed = {"keyword", "active", "notes"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return None

    before = db.get_keyword(keyword_id)
    if not before:
        return None
    before_data = {
        "tier": before.get("tier"), "keyword": before.get("keyword"),
        "active": before.get("active"), "notes": before.get("notes"),
    }
    after = db.update_keyword_raw(keyword_id, safe)
    if not after:
        return None
    after_data = {
        "tier": after.get("tier"), "keyword": after.get("keyword"),
        "active": after.get("active"), "notes": after.get("notes"),
    }
    action = "UPDATE"
    if "active" in safe:
        action = "ACTIVATE" if safe["active"] else "DEACTIVATE"

    db.insert_keyword_change({
        "keyword_id": keyword_id,
        "action": action,
        "tier": after_data["tier"],
        "keyword": after_data["keyword"],
        "before_data": before_data,
        "after_data": after_data,
        "changed_by": changed_by,
        "reason": reason,
    })
    return after_data


def delete_keyword(
    keyword_id: int,
    changed_by: str = "user",
    reason: Optional[str] = None,
) -> bool:
    before = db.get_keyword(keyword_id)
    if not before:
        return False
    before_data = {
        "tier": before.get("tier"), "keyword": before.get("keyword"),
        "active": before.get("active"), "notes": before.get("notes"),
    }
    db.insert_keyword_change({
        "keyword_id": keyword_id,
        "action": "DELETE",
        "tier": before_data["tier"],
        "keyword": before_data["keyword"],
        "before_data": before_data,
        "changed_by": changed_by,
        "reason": reason,
    })
    return db.delete_keyword_raw(keyword_id)


def list_changes(keyword_id: int) -> List[Dict[str, Any]]:
    return db.list_keyword_changes(keyword_id)
