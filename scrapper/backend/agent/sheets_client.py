# sheets_client.py
# Google Sheets storage backend — replaces psycopg2/Postgres.
#
# Architecture (see agent/db.py for the public-facing functions that wrap this):
#
#   1. In-memory MIRROR per tab — every row lives in a `dict[id → record]`.
#      All reads hit RAM (microseconds); only writes touch the network.
#   2. Write BUFFER per tab — queued appends/updates, drained by ONE background
#      flusher thread every SHEETS_FLUSH_SECONDS (or sooner if SHEETS_FLUSH_ROWS
#      worth of rows pile up). One HTTP call writes up to ~500 rows.
#   3. Auto-increment IDs — counter per tab, max(id)+1 computed at bootstrap.
#      No "SELECT max(id)" round-trips on each insert.
#   4. UPSERT semantics — callers pass a `unique_field`; client mutates the
#      existing row in place if a match exists, otherwise appends.
#   5. Retries — Sheets 429/503 get exponential backoff with jitter so a single
#      transient rate-limit doesn't kill a pipeline run.

import atexit
import os
import re
import time
import random
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

from agent.sheets_schema import SCHEMA, TAB_NAMES, EPHEMERAL_TABS, encode_row, decode_row, headers_for

load_dotenv()

# ──────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_ID")
# Service-account creds from individual env vars (preferred in deploy — never
# ship the key in the repo/image). If GOOGLE_CLIENT_EMAIL + GOOGLE_PRIVATE_KEY
# are set, these win over the file fallback (local dev).
CREDS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "./google-credentials.json")


def _creds_info_from_env() -> Optional[Dict[str, str]]:
    """Build a service-account info dict from individual env vars.
    Returns None if the required vars aren't set (caller falls back to file)."""
    client_email = os.getenv("GOOGLE_CLIENT_EMAIL")
    private_key = os.getenv("GOOGLE_PRIVATE_KEY")
    if not client_email or not private_key:
        return None
    # Env vars store newlines as the literal two chars "\n" — restore real ones,
    # otherwise the PEM is malformed and signing fails with "Invalid JWT Signature".
    private_key = private_key.replace("\\n", "\n")
    return {
        "type": "service_account",
        "project_id": os.getenv("GOOGLE_PROJECT_ID", ""),
        "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID", ""),
        "private_key": private_key,
        "client_email": client_email,
        "client_id": os.getenv("GOOGLE_CLIENT_ID", ""),
        "token_uri": os.getenv("GOOGLE_TOKEN_URI", "https://oauth2.googleapis.com/token"),
    }
FLUSH_ROWS = int(os.getenv("SHEETS_FLUSH_ROWS", "200"))
FLUSH_SECONDS = float(os.getenv("SHEETS_FLUSH_SECONDS", "2.0"))

# Worksheet default grid size when we create a new tab. Sheets grows it
# automatically on append, so this is just the initial allocation.
DEFAULT_ROWS = 1000
DEFAULT_COLS = 40


# ──────────────────────────────────────────────────────────────
# Retry wrapper — Sheets 429/500/503 are transient. Exponential backoff
# with jitter prevents a thundering herd from N enrichment workers all
# retrying at the same instant.
# ──────────────────────────────────────────────────────────────
def _with_retry(fn: Callable, *args, max_attempts: int = 6, **kwargs):
    delay = 1.0
    last_err: Optional[Exception] = None
    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            status = getattr(e.response, "status_code", None) if hasattr(e, "response") else None
            msg = str(e)
            # 429 (rate limit) and 5xx (server) are retryable; 4xx are permanent.
            transient = status in (429, 500, 502, 503, 504) or "RATE_LIMIT" in msg.upper() or "Quota" in msg
            if not transient or attempt == max_attempts - 1:
                raise
        except gspread.exceptions.SpreadsheetNotFound:
            # Permanent — don't waste retries.
            raise
            sleep_for = delay + random.uniform(0, delay)
            print(f"⏳ [Sheets] {fn.__name__} retry {attempt + 1}/{max_attempts} after {sleep_for:.1f}s ({msg[:120]})")
            time.sleep(sleep_for)
            delay = min(delay * 2, 30.0)
            last_err = e
        except Exception as e:
            # Network errors etc. — also retry a few times.
            if attempt == max_attempts - 1:
                raise
            sleep_for = delay + random.uniform(0, delay)
            print(f"⏳ [Sheets] {fn.__name__} retry {attempt + 1}/{max_attempts} after {sleep_for:.1f}s ({e})")
            time.sleep(sleep_for)
            delay = min(delay * 2, 30.0)
            last_err = e
    if last_err:
        raise last_err


def _col_letter(n: int) -> str:
    """1 → A, 26 → Z, 27 → AA, etc. — for range strings in batch_update."""
    s = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


_RANGE_START_RE = re.compile(r"![A-Z]+(\d+):")


def _parse_start_row(updated_range: str) -> Optional[int]:
    m = _RANGE_START_RE.search(updated_range)
    return int(m.group(1)) if m else None


# ──────────────────────────────────────────────────────────────
# SheetsDB — the singleton storage handle.
# Process-wide singleton (one client per backend process). Thread-safe.
# ──────────────────────────────────────────────────────────────
class SheetsDB:
    def __init__(self) -> None:
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None
        self.worksheets: Dict[str, gspread.Worksheet] = {}

        # mirror[tab] = dict[id_value -> row_dict]
        # dict preserves insertion order → iteration matches sheet order.
        self.mirror: Dict[str, Dict[Any, Dict[str, Any]]] = {t: {} for t in TAB_NAMES}

        # sheet_row_index[tab][id] = 1-based sheet row (header is row 1).
        # 0 means not yet persisted — still in the append buffer.
        self.sheet_row_index: Dict[str, Dict[Any, int]] = {t: {} for t in TAB_NAMES}

        # Counter for int-id tabs. Lives only in memory; rebuilt at boot from max(id).
        self.counters: Dict[str, int] = {t: 0 for t in TAB_NAMES}

        # pending_writes[tab] = ordered dict[id -> (kind, encoded_row)]
        # kind: 'append' (row hasn't hit the sheet yet) or 'update' (row exists, replace cells).
        # Re-queueing the same id collapses to one entry so we never write the same row twice.
        self.pending_writes: Dict[str, Dict[Any, Tuple[str, List[str]]]] = {t: {} for t in TAB_NAMES}

        # pending_deletes[tab] = list of sheet row indices (descending — delete bottom-up).
        self.pending_deletes: Dict[str, List[int]] = {t: [] for t in TAB_NAMES}

        # Next sheet row to assign when appending. Updated on every successful append.
        self._next_sheet_row: Dict[str, int] = {t: 2 for t in TAB_NAMES}

        self.lock = threading.RLock()
        self._stop = threading.Event()
        self._flusher: Optional[threading.Thread] = None
        self._bootstrapped = False

    # ──────────────────────────────────────────────────────────
    # Auth / open
    # ──────────────────────────────────────────────────────────
    def _connect(self) -> None:
        if not SPREADSHEET_ID:
            raise RuntimeError("GOOGLE_SHEETS_ID not set in .env")

        # Prefer creds from env vars (deploy/secret) — falls back to the file
        # (local dev). This keeps the key out of the repo and the image.
        info = _creds_info_from_env()
        if info:
            creds = Credentials.from_service_account_info(info, scopes=SCOPES)
            print(f"🔑 [Sheets] using env-var credentials "
                  f"(client_email={info.get('client_email')!r})")
        else:
            creds_path = Path(CREDS_FILE)
            if not creds_path.is_absolute():
                # Resolve relative to backend/ (the directory containing .env)
                creds_path = Path(__file__).resolve().parent.parent / creds_path
            if not creds_path.exists():
                raise RuntimeError(
                    f"No credentials: set GOOGLE_CREDENTIALS_JSON env var, or place "
                    f"the service-account file at {creds_path}"
                )
            creds = Credentials.from_service_account_file(str(creds_path), scopes=SCOPES)
        self._client = gspread.authorize(creds)
        self._spreadsheet = _with_retry(self._client.open_by_key, SPREADSHEET_ID)

    # ──────────────────────────────────────────────────────────
    # Bootstrap — idempotent: creates missing tabs, writes header row, loads mirror.
    # Like the old init_schema() but for Sheets.
    # ──────────────────────────────────────────────────────────
    def bootstrap(self) -> None:
        if self._bootstrapped:
            return
        self._connect()

        existing = {ws.title: ws for ws in _with_retry(self._spreadsheet.worksheets)}
        created = 0
        for tab in TAB_NAMES:
            spec_headers = headers_for(tab)
            if tab in existing:
                ws = existing[tab]
                first_row = _with_retry(ws.row_values, 1)
                # Empty tab → write headers. Mismatched headers → keep existing (warn).
                if not first_row:
                    _with_retry(ws.update, [spec_headers], "A1", value_input_option="RAW")
                elif first_row != spec_headers:
                    # Pure additions at the end (existing headers are a prefix of the
                    # schema) → upgrade the header row in place so the sheet stays
                    # self-describing. This is the safe migration path when we append
                    # new columns (e.g. jobs.stop_requested / resume_from).
                    if len(spec_headers) > len(first_row) and spec_headers[:len(first_row)] == first_row:
                        _with_retry(ws.update, [spec_headers], "A1", value_input_option="RAW")
                        print(f"🔧 [Sheets] tab '{tab}' headers extended "
                              f"{len(first_row)}→{len(spec_headers)} cols")
                    else:
                        missing = [h for h in spec_headers if h not in first_row]
                        extra = [h for h in first_row if h not in spec_headers]
                        if missing or extra:
                            print(f"⚠️  [Sheets] tab '{tab}' headers differ from schema "
                                  f"(missing={missing}, extra={extra}) — using schema order.")
            else:
                ws = _with_retry(
                    self._spreadsheet.add_worksheet,
                    title=tab, rows=DEFAULT_ROWS, cols=max(DEFAULT_COLS, len(spec_headers)),
                )
                _with_retry(ws.update, [spec_headers], "A1", value_input_option="RAW")
                created += 1
            self.worksheets[tab] = ws

        if created:
            print(f"✅ [Sheets] created {created} new tabs")

        # 🔎 DIAG — surface which spreadsheet we opened so production logs leave
        # no doubt about which sheet the deploy is talking to.
        try:
            print(f"🔎 [Sheets] opened spreadsheet: title={self._spreadsheet.title!r} "
                  f"id={SPREADSHEET_ID!r}")
        except Exception:
            pass

        self._load_mirror()
        self._start_flusher()
        self._bootstrapped = True
        per_tab = ", ".join(f"{t}={len(self.mirror[t])}" for t in TAB_NAMES)
        print(f"✅ [Sheets] storage ready — "
              f"{sum(len(m) for m in self.mirror.values())} total rows  ({per_tab})")

    def _load_mirror(self) -> None:
        """Pull every tab into memory once. Subsequent reads are dict lookups.

        Ephemeral tabs (EPHEMERAL_TABS) are skipped — they hold large, short-lived
        data and are accessed only via the direct ephemeral_* helpers, never RAM.
        """
        for tab in TAB_NAMES:
            if tab in EPHEMERAL_TABS:
                # Never mirror — keep the mirror dict empty; direct I/O only.
                self._next_sheet_row[tab] = 2
                continue
            ws = self.worksheets[tab]
            all_values = _with_retry(ws.get_all_values)  # single API call per tab
            if len(all_values) <= 1:
                # Empty (header only)
                self._next_sheet_row[tab] = 2
                continue

            # Skip the header row; use schema headers (not sheet's) so column order is canonical.
            id_field = SCHEMA[tab]["id_field"]
            id_kind = SCHEMA[tab]["id_kind"]
            for offset, raw in enumerate(all_values[1:]):
                sheet_row_no = offset + 2  # +2 because header=1, data starts at 2
                rec = decode_row(tab, raw)
                key = rec.get(id_field)
                if key is None:
                    # Skip empty rows the user might have left mid-tab.
                    continue
                self.mirror[tab][key] = rec
                self.sheet_row_index[tab][key] = sheet_row_no
                if id_kind == "int" and isinstance(key, int):
                    if key > self.counters[tab]:
                        self.counters[tab] = key
            self._next_sheet_row[tab] = len(all_values) + 1

    def reload_tab(self, tab: str) -> None:
        """Re-pull ONE tab from Sheets into the mirror, replacing what's there.

        Used in Cloud Run Job mode where the API service and the pipeline worker
        are separate processes sharing the spreadsheet: the service calls this to
        see the worker's live progress. The network fetch happens OUTSIDE the lock
        (only the swap is locked) so reads/writes aren't blocked during the call.

        ⚠️ Only safe to call in a process that does NOT itself buffer writes for
        this tab — otherwise it would clobber un-flushed in-memory changes. The
        worker (jobs-tab writer) must never reload `jobs`; see agent/db.py gating.
        """
        if tab in EPHEMERAL_TABS:
            return
        ws = self.worksheets[tab]
        all_values = _with_retry(ws.get_all_values)  # network: outside the lock
        id_field = SCHEMA[tab]["id_field"]
        id_kind = SCHEMA[tab]["id_kind"]
        new_mirror: Dict[Any, Dict[str, Any]] = {}
        new_index: Dict[Any, int] = {}
        max_counter = self.counters[tab]
        for offset, raw in enumerate(all_values[1:] if len(all_values) > 1 else []):
            rec = decode_row(tab, raw)
            key = rec.get(id_field)
            if key is None:
                continue
            new_mirror[key] = rec
            new_index[key] = offset + 2
            if id_kind == "int" and isinstance(key, int) and key > max_counter:
                max_counter = key
        with self.lock:
            self.mirror[tab] = new_mirror
            self.sheet_row_index[tab] = new_index
            self.counters[tab] = max_counter
            self._next_sheet_row[tab] = (len(all_values) + 1) if all_values else 2

    # ──────────────────────────────────────────────────────────
    # Public read API (all hit RAM)
    # ──────────────────────────────────────────────────────────
    def all_rows(self, tab: str) -> List[Dict[str, Any]]:
        with self.lock:
            return list(self.mirror[tab].values())

    def get_by_id(self, tab: str, id_value: Any) -> Optional[Dict[str, Any]]:
        with self.lock:
            row = self.mirror[tab].get(id_value)
            return dict(row) if row else None

    def find(self, tab: str, predicate: Callable[[Dict[str, Any]], bool]) -> List[Dict[str, Any]]:
        with self.lock:
            return [dict(r) for r in self.mirror[tab].values() if predicate(r)]

    def find_one(self, tab: str, predicate: Callable[[Dict[str, Any]], bool]) -> Optional[Dict[str, Any]]:
        with self.lock:
            for r in self.mirror[tab].values():
                if predicate(r):
                    return dict(r)
        return None

    def count(self, tab: str) -> int:
        with self.lock:
            return len(self.mirror[tab])

    # ──────────────────────────────────────────────────────────
    # Auto-increment counter
    # ──────────────────────────────────────────────────────────
    def next_id(self, tab: str) -> int:
        with self.lock:
            self.counters[tab] += 1
            return self.counters[tab]

    def sync_counter(self, tab: str) -> int:
        """Recompute the counter from max(id) in the mirror. Used by the
        PG→Sheets migration: after inserting rows with caller-supplied ids we
        need the counter to land past the highest one so future next_id()s
        don't collide. Safe to call any time."""
        with self.lock:
            id_field = SCHEMA[tab]["id_field"]
            if SCHEMA[tab]["id_kind"] != "int":
                return self.counters[tab]
            ids = [r.get(id_field) for r in self.mirror[tab].values() if isinstance(r.get(id_field), int)]
            if ids:
                self.counters[tab] = max(self.counters[tab], max(ids))
            return self.counters[tab]

    # ──────────────────────────────────────────────────────────
    # Write API
    # ──────────────────────────────────────────────────────────
    def insert(self, tab: str, record: Dict[str, Any]) -> Dict[str, Any]:
        """Append a new row. record may omit the id field — we'll assign one."""
        spec = SCHEMA[tab]
        id_field = spec["id_field"]
        id_kind = spec["id_kind"]

        with self.lock:
            if record.get(id_field) is None:
                if id_kind == "int":
                    record[id_field] = self.next_id(tab)
                # 'uuid' and 'composite' callers must provide the id themselves.

            key = record[id_field]
            self.mirror[tab][key] = record
            encoded = encode_row(tab, record)
            self.pending_writes[tab][key] = ("append", encoded)
            # New rows haven't been written yet — sheet_row_index gets set on flush.
            self.sheet_row_index[tab].setdefault(key, 0)

        self._maybe_flush_now(tab)
        return dict(record)

    def upsert(self, tab: str, record: Dict[str, Any], unique_field: str) -> Dict[str, Any]:
        """Insert or update keyed by `unique_field`. Returns the final stored record."""
        spec = SCHEMA[tab]
        id_field = spec["id_field"]

        with self.lock:
            existing = None
            unique_val = record.get(unique_field)
            if unique_val is not None:
                for r in self.mirror[tab].values():
                    if r.get(unique_field) == unique_val:
                        existing = r
                        break
            if existing:
                # Preserve the original id, overlay new fields.
                merged = {**existing, **record, id_field: existing[id_field]}
                self.mirror[tab][existing[id_field]] = merged
                encoded = encode_row(tab, merged)
                key = existing[id_field]
                prev = self.pending_writes[tab].get(key)
                # If still pending append → keep as append (new content); otherwise update.
                kind = prev[0] if prev else "update"
                self.pending_writes[tab][key] = (kind, encoded)
                self._maybe_flush_now(tab)
                return dict(merged)

        # No collision — normal insert.
        return self.insert(tab, record)

    def update(self, tab: str, id_value: Any, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Patch an existing row by id. Returns the new record, or None if missing."""
        with self.lock:
            existing = self.mirror[tab].get(id_value)
            if not existing:
                return None
            merged = {**existing, **fields}
            self.mirror[tab][id_value] = merged
            encoded = encode_row(tab, merged)
            prev = self.pending_writes[tab].get(id_value)
            kind = prev[0] if prev else "update"
            self.pending_writes[tab][id_value] = (kind, encoded)
        self._maybe_flush_now(tab)
        return dict(merged)

    def delete(self, tab: str, id_value: Any) -> bool:
        """Remove a row by id. Sheet row is queued for deletion."""
        with self.lock:
            if id_value not in self.mirror[tab]:
                return False
            self.mirror[tab].pop(id_value, None)
            self.pending_writes[tab].pop(id_value, None)
            row_idx = self.sheet_row_index[tab].pop(id_value, 0)
            if row_idx:
                self.pending_deletes[tab].append(row_idx)
        self._maybe_flush_now(tab)
        return True

    def bulk_insert(self, tab: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Insert many rows. Returns the inserted records (with ids assigned)."""
        out: List[Dict[str, Any]] = []
        spec = SCHEMA[tab]
        id_field = spec["id_field"]
        id_kind = spec["id_kind"]

        with self.lock:
            for record in records:
                if record.get(id_field) is None and id_kind == "int":
                    record[id_field] = self.next_id(tab)
                key = record[id_field]
                if key is None:
                    continue
                self.mirror[tab][key] = record
                encoded = encode_row(tab, record)
                self.pending_writes[tab][key] = ("append", encoded)
                self.sheet_row_index[tab].setdefault(key, 0)
                out.append(dict(record))

        self._maybe_flush_now(tab)
        return out

    # ──────────────────────────────────────────────────────────
    # Flusher — drains pending writes to Sheets in big batches.
    # One background thread; one API call per (tab, op) per flush cycle.
    # ──────────────────────────────────────────────────────────
    def _pending_total(self, tab: Optional[str] = None) -> int:
        if tab is not None:
            return len(self.pending_writes[tab]) + len(self.pending_deletes[tab])
        return sum(len(self.pending_writes[t]) + len(self.pending_deletes[t]) for t in TAB_NAMES)

    def _maybe_flush_now(self, tab: str) -> None:
        """Trigger an immediate flush if this tab's pending count crossed the threshold."""
        if self._pending_total(tab) >= FLUSH_ROWS:
            self._flush_tab(tab)

    def _flusher_loop(self) -> None:
        while not self._stop.wait(FLUSH_SECONDS):
            try:
                self.flush_all()
            except Exception as e:
                print(f"⚠️  [Sheets] flusher error (continuing): {e}")

    def _start_flusher(self) -> None:
        if self._flusher and self._flusher.is_alive():
            return
        self._flusher = threading.Thread(target=self._flusher_loop, name="sheets-flusher", daemon=True)
        self._flusher.start()

    def flush_all(self) -> None:
        for tab in TAB_NAMES:
            self._flush_tab(tab)

    def _flush_tab(self, tab: str) -> None:
        """Push every pending row for `tab` to Sheets in one batch each (appends, updates, deletes)."""
        with self.lock:
            pending = self.pending_writes[tab]
            deletes = list(self.pending_deletes[tab])
            self.pending_writes[tab] = {}
            self.pending_deletes[tab] = []

        if not pending and not deletes:
            return

        ws = self.worksheets[tab]
        n_cols = len(SCHEMA[tab]["headers"])
        last_col = _col_letter(n_cols)

        appends: List[Tuple[Any, List[str]]] = []
        updates: List[Tuple[int, List[str]]] = []
        for key, (kind, encoded) in pending.items():
            if kind == "append":
                appends.append((key, encoded))
            else:
                idx = self.sheet_row_index[tab].get(key, 0)
                if idx:
                    updates.append((idx, encoded))
                else:
                    # Row was queued as update but never persisted — treat as append.
                    appends.append((key, encoded))

        try:
            if appends:
                rows = [r for _, r in appends]
                result = _with_retry(
                    ws.append_rows, rows,
                    value_input_option="RAW",
                    insert_data_option="INSERT_ROWS",
                    table_range="A1",
                )
                # Result format: {'spreadsheetId': ..., 'tableRange': ..., 'updates': {'updatedRange': "tab!A5:Z10", ...}}
                updated_range = result.get("updates", {}).get("updatedRange", "")
                start_row = _parse_start_row(updated_range)
                if start_row is None:
                    # Fallback: use our tracked _next_sheet_row.
                    start_row = self._next_sheet_row[tab]
                with self.lock:
                    for offset, (key, _) in enumerate(appends):
                        self.sheet_row_index[tab][key] = start_row + offset
                    self._next_sheet_row[tab] = start_row + len(appends)

            if updates:
                batch = [
                    {"range": f"{tab}!A{idx}:{last_col}{idx}", "values": [row]}
                    for idx, row in updates
                ]
                _with_retry(self._spreadsheet.values_batch_update, {
                    "valueInputOption": "RAW",
                    "data": batch,
                })

            if deletes:
                # Delete rows bottom-up so the indices stay stable while we walk them.
                for row_idx in sorted(set(deletes), reverse=True):
                    _with_retry(ws.delete_rows, row_idx)
                with self.lock:
                    # Shift row indices for surviving rows above each deleted row.
                    deleted_sorted = sorted(set(deletes))
                    for key, idx in list(self.sheet_row_index[tab].items()):
                        if idx in deleted_sorted:
                            self.sheet_row_index[tab].pop(key, None)
                            continue
                        shift = sum(1 for d in deleted_sorted if d < idx)
                        if shift:
                            self.sheet_row_index[tab][key] = idx - shift
                    self._next_sheet_row[tab] = max(2, self._next_sheet_row[tab] - len(deleted_sorted))

        except Exception as e:
            # Re-queue what we tried to flush so it doesn't get lost.
            with self.lock:
                for key, (kind, encoded) in pending.items():
                    self.pending_writes[tab].setdefault(key, (kind, encoded))
                self.pending_deletes[tab].extend(deletes)
            print(f"⚠️  [Sheets] flush failed for '{tab}', requeued {len(pending)} writes: {e}")

    # ──────────────────────────────────────────────────────────
    # Ephemeral-tab I/O — for EPHEMERAL_TABS only. Bypasses the mirror and the
    # write buffer entirely: writes/reads hit Sheets directly. Used for big,
    # short-lived data (pipeline stage checkpoints) that must NOT live in RAM.
    # Only one job runs at a time (enforced by the /start guard), so a checkpoint
    # save safely replaces the whole tab's data region.
    # ──────────────────────────────────────────────────────────
    def ephemeral_write(self, tab: str, encoded_rows: List[List[str]]) -> None:
        """Replace the tab's data (everything below the header) with these rows."""
        ws = self.worksheets[tab]
        last_col = _col_letter(len(SCHEMA[tab]["headers"]))
        _with_retry(ws.batch_clear, [f"A2:{last_col}"])
        if encoded_rows:
            _with_retry(
                ws.append_rows, encoded_rows,
                value_input_option="RAW",
                insert_data_option="INSERT_ROWS",
                table_range="A1",
            )

    def ephemeral_read(self, tab: str) -> List[List[str]]:
        """Return the tab's raw data rows (header stripped). One API call."""
        ws = self.worksheets[tab]
        vals = _with_retry(ws.get_all_values)
        return vals[1:] if len(vals) > 1 else []

    def ephemeral_clear(self, tab: str) -> None:
        """Wipe the tab's data region (keep the header row)."""
        ws = self.worksheets[tab]
        last_col = _col_letter(len(SCHEMA[tab]["headers"]))
        _with_retry(ws.batch_clear, [f"A2:{last_col}"])

    def close(self) -> None:
        self._stop.set()
        if self._flusher:
            self._flusher.join(timeout=5)
        try:
            self.flush_all()
        except Exception as e:
            print(f"⚠️  [Sheets] final flush error: {e}")


# ──────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────
_DB: Optional[SheetsDB] = None
_DB_LOCK = threading.Lock()


def get_db() -> SheetsDB:
    global _DB
    if _DB is None:
        with _DB_LOCK:
            if _DB is None:
                _DB = SheetsDB()
                _DB.bootstrap()
                # The flusher is a daemon thread, so a quick CLI script can exit
                # before pending writes hit the wire. atexit gives the buffer a
                # chance to drain even when there's no explicit close() call.
                atexit.register(_DB.close)
    return _DB