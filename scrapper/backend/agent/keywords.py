# keywords.py
# DB-backed keyword store + CRUD helpers (used by classifier + API routes).
# Wraps agent/db.py keyword functions and adds change-log tracking.

import json
from typing import List, Optional, Dict, Any
from agent.db import _get_conn


def list_keywords(tier: Optional[str] = None) -> List[Dict[str, Any]]:
    from agent.db import list_keywords as _list
    return _list(tier)


def create_keyword(
    tier: str,
    keyword: str,
    notes: Optional[str] = None,
    created_by: str = "user",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Insert new keyword + log change."""
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO keywords (tier, keyword, notes, created_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (tier, keyword) DO NOTHING
                RETURNING id, tier, keyword, active, notes, created_at, updated_at, created_by
                """,
                (tier, keyword.lower(), notes, created_by),
            )
            row = cur.fetchone()
            if not row:
                return {}
            new_id = row[0]
            cur.execute(
                """
                INSERT INTO keyword_changes (keyword_id, action, tier, keyword, after_data, changed_by, reason)
                VALUES (%s, 'CREATE', %s, %s, %s, %s, %s)
                """,
                (new_id, tier, keyword.lower(),
                 json.dumps({"tier": tier, "keyword": keyword.lower(), "active": True, "notes": notes}),
                 created_by, reason),
            )
            return {
                "id": new_id, "tier": row[1], "keyword": row[2], "active": row[3],
                "notes": row[4], "created_by": row[7],
            }
    finally:
        conn.close()


def update_keyword(
    keyword_id: int,
    updates: Dict[str, Any],
    changed_by: str = "user",
    reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update keyword + log change."""
    if not updates:
        return None

    allowed = {"keyword", "active", "notes"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if not safe:
        return None

    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT tier, keyword, active, notes FROM keywords WHERE id = %s", (keyword_id,))
            before = cur.fetchone()
            if not before:
                return None
            before_data = {"tier": before[0], "keyword": before[1], "active": before[2], "notes": before[3]}

            set_clause = ", ".join(f"{k} = %s" for k in safe)
            values = list(safe.values()) + [keyword_id]
            cur.execute(
                f"UPDATE keywords SET {set_clause}, updated_at = NOW() WHERE id = %s",
                values,
            )

            cur.execute("SELECT tier, keyword, active, notes FROM keywords WHERE id = %s", (keyword_id,))
            after = cur.fetchone()
            after_data = {"tier": after[0], "keyword": after[1], "active": after[2], "notes": after[3]}

            action = "UPDATE"
            if "active" in safe:
                action = "ACTIVATE" if safe["active"] else "DEACTIVATE"

            cur.execute(
                """
                INSERT INTO keyword_changes (keyword_id, action, tier, keyword, before_data, after_data, changed_by, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (keyword_id, action, after[0], after[1],
                 json.dumps(before_data), json.dumps(after_data),
                 changed_by, reason),
            )
            return after_data
    finally:
        conn.close()


def delete_keyword(
    keyword_id: int,
    changed_by: str = "user",
    reason: Optional[str] = None,
) -> bool:
    conn = _get_conn()
    try:
        with conn, conn.cursor() as cur:
            cur.execute("SELECT tier, keyword, active, notes FROM keywords WHERE id = %s", (keyword_id,))
            before = cur.fetchone()
            if not before:
                return False
            before_data = {"tier": before[0], "keyword": before[1], "active": before[2], "notes": before[3]}

            cur.execute(
                """
                INSERT INTO keyword_changes (keyword_id, action, tier, keyword, before_data, changed_by, reason)
                VALUES (%s, 'DELETE', %s, %s, %s, %s, %s)
                """,
                (keyword_id, before[0], before[1], json.dumps(before_data), changed_by, reason),
            )
            cur.execute("DELETE FROM keywords WHERE id = %s", (keyword_id,))
            return True
    finally:
        conn.close()


def list_changes(keyword_id: int) -> List[Dict[str, Any]]:
    from psycopg2.extras import RealDictCursor
    conn = _get_conn()
    try:
        with conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM keyword_changes WHERE keyword_id = %s ORDER BY changed_at DESC",
                (keyword_id,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
