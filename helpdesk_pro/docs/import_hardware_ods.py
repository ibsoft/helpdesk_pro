# import_hardware_ods.py
# -*- coding: utf-8 -*-
"""
Import .ods σε PostgreSQL πίνακα hardware_asset με:
- Auto-mapping (EL/EN) + χειροκίνητα overrides (--map/--map-file)
- Timezone-aware timestamps
- Καθάρισμα IPv4 από πεδία τύπου '192.168.10.141 - 7620'
- Εξαγωγή "custom serial" από notes (π.χ. '1408000314 ...' -> custom_tag) και μεταφορά παλιού custom_tag σε notes ως ext=...
- Ενσωμάτωση «ΟΝΟΜ/ΜΟ ΧΡΗΣΤΗ» στα notes ως user=<...>
- Παραγωγή asset_tag από Manufacturer+Model με σειριακή αρίθμηση ανά import: "<Manufacturer> <Model> #<n>"
  ρυθμίσιμη με --asset-tag-seq-start και --asset-tag-seq-prefix
- Χειρισμό UNIQUE στο custom_tag με πολιτική --custom-unique-mode (default: nullify)
- Χειροκίνητο upsert χωρίς ON CONFLICT, key order: serial_number → custom_tag → asset_tag
- Επιβολή status='In Service' σε όλες τις γραμμές
- Per-row transactions ώστε να μην ακυρώνεται όλο το batch

Απαιτήσεις:
  pip install pandas odfpy sqlalchemy psycopg2-binary
"""

import argparse
import os
import sys
import re
import json
import unicodedata
from difflib import SequenceMatcher
from datetime import datetime, date, timezone
from typing import Dict, Any, Optional, List, Tuple

import pandas as pd
from sqlalchemy import create_engine, text, Table, MetaData
from sqlalchemy.engine import Engine

# ----------------------------------------------------------------------
# Config / Globals
# ----------------------------------------------------------------------
DEFAULT_DB_URI = os.getenv(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+psycopg2://postgres:superpass@192.168.1.123:5432/helpdesk_pro"
)

HW_COLUMNS = {
    "asset_tag", "serial_number", "custom_tag", "category", "type",
    "manufacturer", "model", "cpu", "ram_gb", "storage", "gpu",
    "operating_system", "ip_address", "mac_address", "hostname",
    "location", "rack", "status", "condition", "purchase_date",
    "warranty_end", "support_vendor", "support_contract",
    "assigned_to", "assigned_on", "accessories", "power_supply",
    "bios_version", "firmware_version", "notes", "created_at", "updated_at"
}

RAW_SYNONYMS = {
    # EN
    "asset id": "asset_tag", "asset tag": "asset_tag", "tag": "asset_tag", "asset": "asset_tag",
    "custom id": "custom_tag", "custom tag": "custom_tag",
    "serial": "serial_number", "serial no": "serial_number", "sn": "serial_number", "serial number": "serial_number",
    "manufacturer": "manufacturer", "vendor": "manufacturer", "make": "manufacturer",
    "model": "model",
    "category": "category", "type": "type",
    "cpu": "cpu", "processor": "cpu", "ram": "ram_gb", "memory": "ram_gb",
    "storage": "storage", "disk": "storage", "gpu": "gpu", "graphics": "gpu",
    "os": "operating_system", "operating system": "operating_system",
    "ip": "ip_address", "ip address": "ip_address", "mac": "mac_address", "mac address": "mac_address",
    "hostname": "hostname", "host": "hostname",
    "location": "location", "rack": "rack",
    "status": "status", "condition": "condition",
    "purchase date": "purchase_date", "purchasedate": "purchase_date",
    "warranty end": "warranty_end", "warranty": "warranty_end",
    "support vendor": "support_vendor", "support": "support_vendor", "support contract": "support_contract",
    "assigned to": "assigned_to", "assignee": "assigned_to",
    "assigned_on": "assigned_on", "assigned on": "assigned_on",
    "accessories": "accessories", "power supply": "power_supply", "psu": "power_supply",
    "bios": "bios_version", "bios version": "bios_version",
    "firmware": "firmware_version", "firmware version": "firmware_version",
    "notes": "notes", "comment": "notes", "comments": "notes",
    # EL
    "κωδικος παγιου": "asset_tag",
    "ip number": "ip_address",
    "phone number": "custom_tag",
    "τμημα": "location",
    "σχολια": "notes",
    "τηλεφωνο": "model",
    "ετος αγορας": "purchase_date", "ετος αγορασ": "purchase_date",
    "κατασκευαστης": "manufacturer", "κατασκευαστής": "manufacturer", "μαρκα": "manufacturer", "μάρκα": "manufacturer",
    "μοντελο": "model", "μοντέλο": "model",
    "κατηγορια": "category", "κατηγορία": "category", "τυπος": "type", "τύπος": "type",
    "επεξεργαστης": "cpu", "επεξεργαστής": "cpu",
    "μνημη": "ram_gb", "μνήμη": "ram_gb",
    "δισκος": "storage", "δίσκος": "storage",
    "λειτουργικο": "operating_system", "λειτουργικό": "operating_system",
    "διευθυνση ip": "ip_address", "διεύθυνση ip": "ip_address",
    "διευθυνση mac": "mac_address", "διεύθυνση mac": "mac_address",
    "ονομα υπολογιστη": "hostname", "όνομα υπολογιστή": "hostname",
    "κατασταση": "status", "κατάσταση": "status",
    "φθορα": "condition", "κατάσταση/φθορά": "condition",
    "προμηθευτης υποστηριξης": "support_vendor",
    "συμβολαιο υποστηριξης": "support_contract",
    "υπευθυνος": "assigned_to",
    "ημερομηνια αναθεσης": "assigned_on", "ημερομηνία ανάθεσης": "assigned_on",
    "παρελκομενα": "accessories", "παρελκόμενα": "accessories",
    "τροφοδοτικο": "power_supply", "τροφοδοτικό": "power_supply",
    "σημειωσεις": "notes", "σημειώσεις": "notes",
    "σειριακος": "serial_number", "σειριακός": "serial_number",
    "σειριακος αριθμος": "serial_number", "σειριακός αριθμός": "serial_number",
}

DATE_COLUMNS = {"purchase_date", "warranty_end", "assigned_on", "created_at", "updated_at"}
KEY_COLUMNS_AS_TEXT = {"asset_tag", "custom_tag", "serial_number"}

KEY_ORDER = ("serial_number", "custom_tag", "asset_tag")
CUSTOM_UNIQUE_MODE = "nullify"  # update | nullify | skip

ASSET_TAG_SEP = " "

# Σειριακή αρίθμηση asset_tag
ASSET_TAG_SEQ_START = 1
ASSET_TAG_SEQ_PREFIX = "#"

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")

def normalise_header(h: str) -> str:
    base = strip_accents(h or "")
    base = re.sub(r"[_\-\.\:/\\]+", " ", base.strip().lower())
    base = re.sub(r"\s+", " ", base)
    return base

def build_synonyms() -> Dict[str, str]:
    syn = {}
    for k, v in RAW_SYNONYMS.items():
        syn[normalise_header(k)] = v
    for col in HW_COLUMNS:
        syn[normalise_header(col)] = col
    return syn

SYNONYMS = build_synonyms()

def fuzzy_guess(target_map: Dict[str, str], key_norm: str) -> Optional[str]:
    for syn_key, tgt in target_map.items():
        if syn_key and len(syn_key) >= 3 and syn_key in key_norm:
            return tgt
    best_tgt, best_score = None, 0.0
    for syn_key, tgt in target_map.items():
        if not syn_key:
            continue
        score = SequenceMatcher(None, syn_key, key_norm).ratio()
        if score > best_score:
            best_score, best_tgt = score, tgt
    return best_tgt if best_score >= 0.82 else None

def map_header_to_column(h: str) -> Optional[str]:
    key = normalise_header(str(h))
    if key in SYNONYMS:
        return SYNONYMS[key]
    return fuzzy_guess(SYNONYMS, key)

# ----------------------------------------------------------------------
# Value coercion
# ----------------------------------------------------------------------
_ipv4_re = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_first_int_re = re.compile(r"\b(\d{6,})\b")  # πρώτο συνεχές ψηφίο ≥6

def parse_date(val: Any) -> Optional[date]:
    if val is None or (isinstance(val, float) and pd.isna(val)) or (isinstance(val, str) and not val.strip()):
        return None
    if isinstance(val, (pd.Timestamp, datetime)):
        if isinstance(val, datetime):
            return val.astimezone(timezone.utc).date() if val.tzinfo else val.date()
        return val.date()
    if isinstance(val, date):
        return val
    try:
        return pd.to_datetime(val, dayfirst=True, errors="raise").date()
    except Exception:
        return None

def coerce_value(col: str, val: Any) -> Any:
    if pd.isna(val):
        return None
    if col in KEY_COLUMNS_AS_TEXT:
        return str(val).strip()
    if col in DATE_COLUMNS:
        v = parse_date(val)
        if v is None:
            s = str(val).strip()
            if s.isdigit() and len(s) in (2, 4):
                yr = int(s) if len(s) == 4 else int("20" + s)
                return date(yr, 1, 1)
        return v
    if col == "ip_address":
        s = str(val).strip()
        m = _ipv4_re.search(s)
        return m.group(0) if m else s
    if col == "mac_address":
        return str(val).strip().lower().replace("-", ":")
    if col == "ram_gb":
        return str(val).strip()
    if col == "model":
        return str(val).strip()
    return val

def choose_conflict_target(row: Dict[str, Any]) -> Optional[str]:
    for key in KEY_ORDER:
        v = row.get(key)
        if v and str(v).strip():
            return key
    return None

# ----------------------------------------------------------------------
# I/O and mapping
# ----------------------------------------------------------------------
def load_ods(path: str, sheet: Optional[str]) -> pd.DataFrame:
    return pd.read_excel(path, sheet_name=sheet if sheet else 0, engine="odf", dtype=object)

def preview_columns(df: pd.DataFrame, sample_rows: int = 3) -> None:
    print("\n[columns] Εντοπίστηκαν στήλες:")
    for c in df.columns:
        cn = normalise_header(str(c))
        print(f"  - raw: '{c}'  | norm: '{cn}'")
    print("\n[sample] Δείγμα πρώτων γραμμών:")
    try:
        print(df.head(sample_rows).to_string(index=False))
    except Exception:
        print(df.head(sample_rows))

def apply_manual_map(header_map: Dict[str, str], manual_map: Dict[str, str], df: pd.DataFrame) -> Dict[str, str]:
    if not manual_map:
        return header_map
    raw_to_norm = {str(c): normalise_header(str(c)) for c in df.columns}
    norm_to_raw = {v: k for k, v in raw_to_norm.items()}
    for src, tgt in manual_map.items():
        src_norm = normalise_header(src)
        raw = norm_to_raw.get(src_norm, src)
        if tgt not in HW_COLUMNS:
            print(f"[!] Αγνόηση manual map '{src} -> {tgt}': άγνωστος προορισμός.")
            continue
        if raw in df.columns:
            header_map[raw] = tgt
        else:
            for real_raw, norm in raw_to_norm.items():
                if norm == src_norm:
                    header_map[real_raw] = tgt
                    break
    return header_map

def compose_asset_base(row: Dict[str, Any]) -> Optional[str]:
    manu = (row.get("manufacturer") or "").strip()
    model = (row.get("model") or "").strip()
    if manu and model:
        return f"{manu}{ASSET_TAG_SEP}{model}".strip()
    return (manu or model or None)

def find_user_name_column(df: pd.DataFrame) -> Optional[str]:
    targets = {"ονομ μο χρηστη", "ονομα χρηστη", "ονομα χρηστης", "χρηστης", "user", "user name", "username", "user full name"}
    candidates = []
    for c in df.columns:
        cn = normalise_header(str(c))
        if cn in targets:
            return c
        score = max(SequenceMatcher(None, cn, t).ratio() for t in targets)
        candidates.append((score, c))
    best = max(candidates, default=(0, None))
    return best[1] if best[0] >= 0.85 else None

def build_mapped_rows(df: pd.DataFrame, manual_map: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    header_map: Dict[str, str] = {}
    for c in df.columns:
        tgt = map_header_to_column(str(c))
        if tgt:
            header_map[str(c)] = tgt
    if manual_map:
        header_map = apply_manual_map(header_map, manual_map, df)
    if not header_map:
        print("[!] Δεν έγινε ταίριασμα καμίας στήλης. Έλεγξε τα headers ή χρησιμοποίησε --print-columns / --map.")
    user_col_raw = find_user_name_column(df)

    mapped: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for _, r in df.iterrows():
        row: Dict[str, Any] = {}
        for src, tgt in header_map.items():
            row[tgt] = coerce_value(tgt, r.get(src))
        row["status"] = "In Service"
        if user_col_raw and user_col_raw in df.columns:
            uname = r.get(user_col_raw)
            uname = None if (pd.isna(uname) or uname is None) else str(uname).strip()
            if uname:
                existing = (row.get("notes") or "").strip()
                sep = " | " if existing else ""
                row["notes"] = f"{existing}{sep}user={uname}"
        if not row.get("created_at"):
            row["created_at"] = now
        row["updated_at"] = now
        mapped.append(row)

    postprocess_rows(mapped)
    return mapped, header_map

def postprocess_rows(rows: List[Dict[str, Any]]) -> None:
    # Συμπλήρωσε manufacturer από model αν λείπει
    for row in rows:
        model = (row.get("model") or "").strip()
        manufacturer = (row.get("manufacturer") or "").strip()
        if model and not manufacturer:
            parts = model.split()
            if len(parts) >= 2 and parts[0].isalpha():
                row["manufacturer"] = parts[0]
                row["model"] = " ".join(parts[1:])

    # Εξαγωγή custom serial από notes
    for row in rows:
        notes = (row.get("notes") or "").strip()
        m = _first_int_re.search(notes) if notes else None
        if m:
            custom_serial = m.group(1)
            current_ct = (row.get("custom_tag") or "").strip()
            if current_ct and current_ct != custom_serial:
                prefix = " | " if notes else ""
                row["notes"] = f"{notes}{prefix}ext={current_ct}"
            row["custom_tag"] = custom_serial

    # Παραγωγή asset_tag βάσης από Manufacturer+Model
    for row in rows:
        base = compose_asset_base(row)
        row["asset_tag"] = base or "Unknown"

    # Σειριακή αρίθμηση asset_tag ανά import: "<base> #<n>"  (ΤΕΛΟΣ)
    n = ASSET_TAG_SEQ_START
    for row in rows:
        base = (row.get("asset_tag") or "Unknown").strip()
        row["asset_tag"] = f"{base} {ASSET_TAG_SEQ_PREFIX}{n}"
        n += 1

# ----------------------------------------------------------------------
# DB
# ----------------------------------------------------------------------
def reflect_hardware_table(engine: Engine) -> Table:
    metadata = MetaData()
    return Table("hardware_asset", metadata, autoload_with=engine)

def _update_by_id(conn, row_update: Dict[str, Any], rec_id: int) -> None:
    update_row = {k: v for k, v in row_update.items() if k not in ("id", "created_at")}
    if not update_row:
        return
    set_clause = ", ".join([f"{k} = :{k}" for k in update_row.keys()])
    params = dict(update_row)
    params["id"] = rec_id
    sql = text(f"UPDATE hardware_asset SET {set_clause} WHERE id = :id")
    conn.execute(sql, params)

def manual_upsert(conn, table: Table, row: Dict[str, Any]) -> str:
    """Χειροκίνητο upsert. Key order: serial_number → custom_tag → asset_tag."""
    valid_row = {k: v for k, v in row.items() if k in table.c}

    conflict_col = choose_conflict_target(valid_row)
    if not conflict_col:
        return "skip"

    conflict_val = str(valid_row.get(conflict_col)).strip()
    rec = conn.execute(
        text(f"SELECT id FROM hardware_asset WHERE {conflict_col}::text = :v LIMIT 1"),
        {"v": conflict_val}
    ).fetchone()

    if rec:
        _update_by_id(conn, valid_row, rec[0])
        return "update"

    # Έλεγχος custom_tag collisions πριν το insert
    ct = valid_row.get("custom_tag")
    if ct is not None and str(ct).strip():
        ct_rec = conn.execute(
            text("SELECT id FROM hardware_asset WHERE custom_tag::text = :c LIMIT 1"),
            {"c": str(ct).strip()}
        ).fetchone()
        if ct_rec:
            modec = (CUSTOM_UNIQUE_MODE or "nullify").lower()
            if modec == "update":
                _update_by_id(conn, valid_row, ct_rec[0])
                return "update"
            elif modec == "nullify":
                n = (valid_row.get("notes") or "")
                sep = " | " if n else ""
                valid_row["notes"] = f"{n}{sep}acct_code={ct}"
                valid_row["custom_tag"] = None
            elif modec == "skip":
                return "skip"

    cols = ", ".join(valid_row.keys())
    vals = ", ".join([f":{k}" for k in valid_row.keys()])
    sql = text(f"INSERT INTO hardware_asset ({cols}) VALUES ({vals})")
    conn.execute(sql, valid_row)
    return "insert"

def upsert_rows(engine: Engine, table: Table, rows: List[Dict[str, Any]], dry_run: bool = False):
    if not rows:
        print("[i] Δεν βρέθηκαν εγγραφές προς εισαγωγή.")
        return
    inserted = updated = skipped = 0

    if dry_run:
        with engine.connect() as conn:
            for row in rows:
                try:
                    valid_row = {k: v for k, v in row.items() if k in table.c}
                    key = choose_conflict_target(valid_row)
                    val = str(valid_row.get(key)).strip() if key else None
                    exists = False
                    if key and val:
                        rec = conn.execute(
                            text(f"SELECT 1 FROM hardware_asset WHERE {key}::text = :v LIMIT 1"),
                            {"v": val}
                        ).fetchone()
                        exists = rec is not None

                    if exists:
                        print(f"[dry-run] update on {key}='{val}': {valid_row}")
                        updated += 1
                        continue

                    # custom_tag collision
                    ct = valid_row.get("custom_tag")
                    if ct is not None and str(ct).strip():
                        ct_rec = conn.execute(
                            text("SELECT 1 FROM hardware_asset WHERE custom_tag::text = :c LIMIT 1"),
                            {"c": str(ct).strip()}
                        ).fetchone()
                        if ct_rec:
                            if (CUSTOM_UNIQUE_MODE or "nullify").lower() == "update":
                                print(f"[dry-run] update due to existing custom_tag='{ct}': {valid_row}")
                                updated += 1
                                continue
                            elif (CUSTOM_UNIQUE_MODE or "nullify").lower() == "nullify":
                                vr = dict(valid_row)
                                n = (vr.get("notes") or "")
                                sep = " | " if n else ""
                                vr["notes"] = f"{n}{sep}acct_code={ct}"
                                vr["custom_tag"] = None
                                print(f"[dry-run] insert(nullify-custom_tag->notes) on {key}='{val}': {vr}")
                                inserted += 1
                                continue
                            else:
                                print(f"[dry-run] skip due to existing custom_tag='{ct}': {valid_row}")
                                skipped += 1
                                continue

                    print(f"[dry-run] insert on {key}='{val}': {valid_row}")
                    inserted += 1
                except Exception as e:
                    skipped += 1
                    print(f"[!] Σφάλμα στη γραμμή (dry-run): {e} | row={row}")
        print(f"[✓] Προσομοίωση ολοκληρώθηκε: would-insert={inserted}, would-update={updated}, would-skip={skipped}")
        return

    with engine.connect() as conn:
        for row in rows:
            tx = conn.begin()
            try:
                action = manual_upsert(conn, table, row)
                if action == "insert":
                    inserted += 1
                elif action == "update":
                    updated += 1
                else:
                    skipped += 1
                tx.commit()
            except Exception as e:
                tx.rollback()
                skipped += 1
                print(f"[!] Σφάλμα στη γραμμή: {e} | row={row}")

    print(f"[✓] Ολοκληρώθηκε: inserted={inserted}, updated={updated}, skipped={skipped}")

# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def parse_manual_map_arg(map_arg: Optional[str]) -> Dict[str, str]:
    if not map_arg:
        return {}
    out: Dict[str, str] = {}
    parts = [p.strip() for p in map_arg.split(",") if p.strip()]
    for p in parts:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def load_map_file(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {str(k): str(v) for k, v in data.items()}

def main():
    global KEY_ORDER, CUSTOM_UNIQUE_MODE, ASSET_TAG_SEQ_START, ASSET_TAG_SEQ_PREFIX, ASSET_TAG_SEP

    parser = argparse.ArgumentParser(
        description="Import .ods σε hardware_asset (PostgreSQL) με χειροκίνητο upsert."
    )
    parser.add_argument("ods_path", help="Μονοπάτι στο αρχείο .ods")
    parser.add_argument("--db", dest="db_uri", default=DEFAULT_DB_URI, help="SQLAlchemy DB URI")
    parser.add_argument("--sheet", dest="sheet", default=None, help="Όνομα ή index φύλλου (προεπιλογή: 0)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Χωρίς εγγραφή στη ΒΔ, μόνο προεπισκόπηση")
    parser.add_argument("--print-columns", dest="print_cols", action="store_true", help="Εκτύπωση headers/δειγμάτων και έξοδος")
    parser.add_argument("--map", dest="map_arg", default=None, help='Manual overrides, π.χ. --map "Extension=custom_tag, MAC=mac_address"')
    parser.add_argument("--map-file", dest="map_file", default=None, help="JSON με manual mapping {source: target, ...}")
    parser.add_argument("--key-order", dest="key_order", default="serial_number,custom_tag,asset_tag",
                        help="Σειρά προτεραιότητας κλειδιών ταυτοποίησης (comma-sep).")
    parser.add_argument("--custom-unique-mode", dest="custom_unique_mode",
                        choices=["update", "nullify", "skip"], default="nullify",
                        help="Αν το custom_tag υπάρχει ήδη: update, nullify (default), ή skip.")
    parser.add_argument("--asset-tag-sep", dest="asset_tag_sep", default=" ",
                        help="Διαχωριστικό μεταξύ manufacturer και model.")
    parser.add_argument("--asset-tag-seq-start", dest="asset_tag_seq_start", type=int, default=1,
                        help="Αρχικός αύξων αριθμός για το asset_tag (default: 1).")
    parser.add_argument("--asset-tag-seq-prefix", dest="asset_tag_seq_prefix", default="#",
                        help="Πρόθεμα αύξοντα (default: '#').")

    args = parser.parse_args()

    KEY_ORDER = tuple(x.strip() for x in (args.key_order or "").split(",") if x.strip()) or KEY_ORDER
    CUSTOM_UNIQUE_MODE = args.custom_unique_mode
    ASSET_TAG_SEP = args.asset_tag_sep
    ASSET_TAG_SEQ_START = int(args.asset_tag_seq_start or 1)
    ASSET_TAG_SEQ_PREFIX = args.asset_tag_seq_prefix or "#"

    ods_path = args.ods_path
    if not os.path.exists(ods_path):
        print(f"[!] Δεν βρέθηκε αρχείο: {ods_path}")
        sys.exit(1)

    print(f"[i] Διαβάζω: {ods_path}")
    df = load_ods(ods_path, args.sheet)

    if df.empty:
        print("[!] Το .ods δεν έχει δεδομένα.")
        sys.exit(0)

    if args.print_cols:
        preview_columns(df)
        sys.exit(0)

    manual_map = load_map_file(args.map_file)
    manual_map.update(parse_manual_map_arg(args.map_arg))

    print(f"[i] Εντοπίστηκαν {len(df)} γραμμές. Προετοιμασία χαρτογράφησης…")
    rows, header_map = build_mapped_rows(df, manual_map=manual_map)

    print(f"[i] Σύνδεση στη ΒΔ: {args.db_uri}")
    engine = create_engine(args.db_uri)

    try:
        table = reflect_hardware_table(engine)
    except Exception as e:
        print(f"[!] Αποτυχία ανάγνωσης σχήματος πίνακα 'hardware_asset': {e}")
        sys.exit(2)

    if rows:
        print("\n[map] Χαρτογράφηση που θα χρησιμοποιηθεί:")
        for src, tgt in header_map.items():
            print(f"  '{src}'  →  {tgt}")

    upsert_rows(engine, table, rows, dry_run=args.dry_run)

if __name__ == "__main__":
    main()

