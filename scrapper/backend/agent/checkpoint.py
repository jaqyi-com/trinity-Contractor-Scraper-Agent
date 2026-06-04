# checkpoint.py
# Pipeline stop/resume checkpoints, stored in the non-mirrored `stage_outputs`
# tab (see sheets_schema.EPHEMERAL_TABS). The working row-set at a phase boundary
# is serialised here so a paused/failed run can resume WITHOUT re-running the
# expensive discovery (Apify/Google) stage.
#
# Why not the in-RAM mirror / a normal tab: the set can be 15-25k rows and would
# re-introduce the 512MB OOM. Ephemeral I/O streams straight to Sheets instead.
#
# Layout: items are JSON-chunked (CHUNK per cell) across stage_outputs rows so the
# row count stays low and each cell stays well under the 50k-char Sheets limit.
# Only ONE checkpoint exists at a time — saving replaces the whole tab region.

from datetime import datetime
from typing import Any, Dict, List, Optional

from agent.sheets_client import get_db
from agent.sheets_schema import encode_row, decode_row
from agent.schema import GoogleSeed, ContractorRow

TAB = "stage_outputs"
CHUNK = 20  # items per cell — keeps each JSON cell well under Sheets' 50k-char cap

# resume_from stage name → pydantic model the carried items deserialise back into.
# None means the stage needs no carried payload (data already persisted elsewhere).
STAGE_MODEL = {
    "dedupe_seeds": GoogleSeed,
    "classify": GoogleSeed,
    "cap": ContractorRow,
    "enrich": ContractorRow,
    "dedupe_final": None,
}


def save_checkpoint(job_id: str, next_stage: str, items: list) -> None:
    """Persist `items` as the resume point for `next_stage`, replacing any prior
    checkpoint. `items` are pydantic models (GoogleSeed / ContractorRow)."""
    db = get_db()
    dicts: List[Dict[str, Any]] = []
    for it in items:
        d = it.model_dump(mode="json") if hasattr(it, "model_dump") else dict(it)
        d.pop("raw", None)  # audit-only blob, large, not needed to resume
        dicts.append(d)

    now = datetime.utcnow()
    rows: List[List[str]] = []
    for idx, start in enumerate(range(0, len(dicts), CHUNK)):
        rows.append(encode_row(TAB, {
            "id": idx + 1,
            "job_id": job_id,
            "stage_name": next_stage,
            "row_index": idx,
            "data": dicts[start:start + CHUNK],
            "created_at": now,
        }))
    db.ephemeral_write(TAB, rows)
    print(f"💾 [checkpoint] saved {len(dicts)} items → resume@{next_stage} "
          f"({len(rows)} chunk rows)")


def load_checkpoint() -> Optional[Dict[str, Any]]:
    """Return {'stage', 'job_id', 'items'} from the stored checkpoint, or None.
    `items` are rebuilt into the pydantic model for that stage."""
    db = get_db()
    raw = db.ephemeral_read(TAB)
    if not raw:
        return None
    decoded = [decode_row(TAB, r) for r in raw]
    decoded = [d for d in decoded if d.get("stage_name")]
    if not decoded:
        return None
    decoded.sort(key=lambda d: d.get("row_index") or 0)

    stage = decoded[0]["stage_name"]
    job_id = decoded[0].get("job_id")
    model = STAGE_MODEL.get(stage)

    items: list = []
    for d in decoded:
        for item in (d.get("data") or []):
            items.append(model(**item) if model else item)
    print(f"📂 [checkpoint] loaded {len(items)} items → resume@{stage}")
    return {"stage": stage, "job_id": job_id, "items": items}


def clear_checkpoint() -> None:
    """Drop the current checkpoint (called on completion / cancel)."""
    get_db().ephemeral_clear(TAB)
