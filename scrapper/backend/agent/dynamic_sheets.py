# dynamic_sheets.py
# Per-run RESULT spreadsheets. Each pipeline run creates its own Google Sheet (in
# a shared Drive folder) holding that run's contractor rows, each tagged with a
# `change_status` of new / updated / unchanged (Option A). The cumulative
# `contractors` master tab and all its logic are UNCHANGED — this is additive.
#
# Why separate spreadsheets (not tabs in the main sheet): keeps each weekly run's
# deliverable self-contained + named by date, and avoids growing the mirrored
# main spreadsheet (the 512MB / 10M-cell concern).
#
# Config (env):
#   DRIVE_RESULTS_FOLDER_ID — Drive folder (shared with the service account as
#                             Editor) where new sheets are created. If unset, the
#                             feature is OFF (pipeline just skips it).
#   RESULTS_SHARE_WITH      — optional email to also share each new sheet with, so
#                             a human can open it.

import os
from typing import Any, Dict, List, Optional, Tuple

from agent.sheets_client import get_db, _with_retry, _col_letter
from agent.sheets_schema import SCHEMA, encode_row, decode_row

FOLDER_ID = os.getenv("DRIVE_RESULTS_FOLDER_ID")
SHARE_WITH = os.getenv("RESULTS_SHARE_WITH")

WORKSHEET = "contractors"
# Result sheet = contractor columns + the per-run change_status column.
RESULT_HEADERS: List[str] = SCHEMA["contractors"]["headers"] + ["change_status"]


def is_enabled() -> bool:
    return bool(FOLDER_ID)


def create_run_sheet(job_id: str, when_label: str) -> Tuple[str, str, str]:
    """Create a new spreadsheet for this run in the shared folder. Returns
    (spreadsheet_id, url, title). The title carries the date + a short job id."""
    client = get_db().gspread_client()
    title = f"Contractors {when_label} · job {job_id[:8]}"

    sh = _with_retry(client.create, title, folder_id=FOLDER_ID) if FOLDER_ID \
        else _with_retry(client.create, title)

    ws = sh.sheet1
    _with_retry(ws.update_title, WORKSHEET)
    _with_retry(ws.update, [RESULT_HEADERS], "A1", value_input_option="RAW")

    if SHARE_WITH:
        try:
            _with_retry(sh.share, SHARE_WITH, perm_type="user", role="writer")
        except Exception as e:
            print(f"⚠️  [dynamic-sheet] could not share with {SHARE_WITH}: {e}")

    url = f"https://docs.google.com/spreadsheets/d/{sh.id}"
    print(f"📄 [dynamic-sheet] created '{title}' → {url}")
    return sh.id, url, title


def write_run_rows(spreadsheet_id: str, rows_with_status: List[Dict[str, Any]]) -> None:
    """Replace the result sheet's data with these rows. Each dict is a contractor
    record plus a 'change_status' key. Idempotent (clears first) so a resumed run
    can rewrite the same sheet."""
    client = get_db().gspread_client()
    sh = _with_retry(client.open_by_key, spreadsheet_id)
    ws = _with_retry(sh.worksheet, WORKSHEET)

    last_col = _col_letter(len(RESULT_HEADERS))
    _with_retry(ws.batch_clear, [f"A2:{last_col}"])

    encoded = [
        encode_row("contractors", rec) + [str(rec.get("change_status") or "")]
        for rec in rows_with_status
    ]
    if encoded:
        _with_retry(
            ws.append_rows, encoded,
            value_input_option="RAW",
            insert_data_option="INSERT_ROWS",
            table_range="A1",
        )
    print(f"📄 [dynamic-sheet] wrote {len(encoded)} rows to {spreadsheet_id}")


def read_run_rows(spreadsheet_id: str) -> List[Dict[str, Any]]:
    """Read a result sheet back into contractor dicts (+ change_status). Used by
    the API when the UI views a specific run's sheet."""
    client = get_db().gspread_client()
    sh = _with_retry(client.open_by_key, spreadsheet_id)
    ws = _with_retry(sh.worksheet, WORKSHEET)
    values = _with_retry(ws.get_all_values)
    out: List[Dict[str, Any]] = []
    for raw in values[1:] if len(values) > 1 else []:
        # decode the contractor columns; the extra change_status is the last cell.
        rec = decode_row("contractors", raw)
        rec["change_status"] = raw[len(SCHEMA["contractors"]["headers"])] \
            if len(raw) > len(SCHEMA["contractors"]["headers"]) else None
        if rec.get("business_name"):
            out.append(rec)
    return out
