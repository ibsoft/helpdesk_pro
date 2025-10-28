# import_hardware_ods.py
# -*- coding: utf-8 -*-
"""
Import .ods/.xlsx -> PostgreSQL hardware_asset χωρίς καμία «μοναδικότητα» στο asset_tag.
- Ταυτοποίηση/Upsert με: serial_number → custom_tag (asset_tag δεν χρησιμοποιείται για ταυτοποίηση)
- Δεν γίνεται έλεγχος uniqueness στο asset_tag
- asset_tag: από Manufacturer+Model (ή διατηρείται αν υπάρχει)· επιλογή τρόπου με --asset-tag-mode
- Εξαγωγή λογιστικού αριθμού από notes -> custom_tag (πρώτος ακέραιος ≥6 ψηφία), παλιό custom_tag → notes ως ext=<...>
- Προσθήκη user=<...> από στήλη «ΟΝΟΜ/ΜΟ ΧΡΗΣΤΗ» στα notes
- Καθάρισμα IPv4 από τιμές τύπου "192.168.10.141 - 7620"
- Timezone-aware timestamps
- Per-row transactions (ένα λάθος δεν ρίχνει όλο το batch)
- --custom-unique-mode: update|nullify|skip  (default: nullify)
- --category και --type για καθολική τιμή Category/Type ανά import
- --map / --map-file για manual mapping
Απαιτήσεις: pip install pandas odfpy openpyxl sqlalchemy psycopg2-binary
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

SYSTEM_PROMPT_TEXT = """You are Helpdesk Pro's IT operations assistant. You can query the internal PostgreSQL database in read-only mode. It is organised into these modules:

- Tickets → table `ticket` (id, subject, status, priority, department, created_by, assigned_to, created_at, updated_at, closed_at) with related tables `ticket_comment`, `attachment`, and `audit_log`.
- Knowledge Base → tables `knowledge_article`, `knowledge_article_version`, `knowledge_attachment` containing published procedures, summaries, tags, and version history.
- Inventory → tables `hardware_asset` (asset_tag, serial_number, hostname, ip_address, location, status, assigned_to, warranty_end, notes) and `software_asset` (name, version, license_type, custom_tag, assigned_to, expiration_date, deployment_notes).
- Network → tables `network` (name, cidr, site, vlan, gateway) and `network_host` (network_id, ip_address, hostname, mac_address, device_type, assigned_to, is_reserved).

When responding:
1. Identify which tables contain the answer and build the appropriate SELECT queries with filters (for example, `status = 'Open'` and date checks for today's tickets).
2. Use the returned rows to craft a concise, actionable summary. Reference key identifiers such as ticket ids, article titles, asset tags, or IP addresses.
3. Clearly note assumptions, and if no rows match, state that nothing was found and suggest next steps.
Only answer with information that exists in these modules. If a request falls outside this data, explain the limitation.
4. You may include license keys exactly as stored in the database when responding to authorized inventory queries."""

# ----------------------------------------------------------------------
# Defaults / Columns
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

# Ταυτοποίηση μόνο με αυτά τα δύο:
KEY_ORDER = ("serial_number", "custom_tag")

# Χειρισμός uniqueness μόνο για custom_tag (αν υπάρχει unique index στη ΒΔ)
CUSTOM_UNIQUE_MODE = "nullify"  # update|nullify|skip

ASSET_TAG_SEP = " "

# σταθερές τιμές Category/Type από CLI
FIXED_CATEGORY: Optional[str] = None
FIXED_TYPE: Optional[str] = None

# asset_tag mode: keep | from-model | from-model-numbered
ASSET_TAG_MODE = "keep"
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
_first_int_re = re.compile(r"\b(\d{6,})\b")  # πρώτος συνεχόμενος ακέραιος >= 6 ψηφία

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
    ext = os.path.splitext(path.lower())[1]
    if ext == ".ods":
        return pd.read_excel(path, sheet_name=sheet if sheet else 0, engine="odf", dtype=object)
    else:
        return pd.read_excel(path, sheet_name=sheet if sheet else 0, dtype=object)  # openpyxl για .xlsx

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

def find_user_name_column(df: pd.DataFrame) -> Optional[str]:
    targets = {"ονομ μο χρηστη", "ονομα χρηστη", "ονομα χρηστης", "χρηστης",
               "user", "user name", "username", "user full name"}
    best = (0.0, None)
    for c in df.columns:
        cn = normalise_header(str(c))
        if cn in targets:
            return c
        score = max(SequenceMatcher(None, cn, t).ratio() for t in targets)
        if score > best[0]:
            best = (score, c)
    return best[1] if best[0] >= 0.85 else None

def compose_asset_from_model(row: Dict[str, Any]) -> Optional[str]:
    manu = (row.get("manufacturer") or "").strip()
    model = (row.get("model") or "").strip()
    if manu and model:
        return f"{manu}{ASSET_TAG_SEP}{model}".strip()
    return (manu or model or None)

def build_mapped_rows(df: pd.DataFrame, manual_map: Optional[Dict[str, str]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    header_map: Dict[str, str] = {}
    for c in df.columns:
        tgt = map_header_to_column(str(c))
        if tgt:
            header_map[str(c)] = tgt
    if manual_map:
        header_map = apply_manual_map(header_map, manual_map, df)
    if not header_map:
        print("[!] Δεν έγινε ταίριασμα καμίας στήλης. Έλεγξε headers ή --print-columns/--map.")
        return [], {}

    user_col_raw = find_user_name_column(df)

    mapped: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for _, r in df.iterrows():
        row: Dict[str, Any] = {}
        for src, tgt in header_map.items():
            row[tgt] = coerce_value(tgt, r.get(src))

        # σταθερές κατηγορίες/τύπος από CLI, αν δόθηκαν
        if FIXED_CATEGORY:
            row["category"] = FIXED_CATEGORY
        if FIXED_TYPE:
            row["type"] = FIXED_TYPE

        # status
        row["status"] = "In Service"

        # user -> notes
        if user_col_raw and user_col_raw in df.columns:
            uname = r.get(user_col_raw)
            uname = None if (pd.isna(uname) or uname is None) else str(uname).strip()
            if uname:
                existing = (row.get("notes") or "").strip()
                sep = " | " if existing else ""
                row["notes"] = f"{existing}{sep}user={uname}"

        # timestamps
        if not row.get("created_at"):
            row["created_at"] = now
        row["updated_at"] = now

        mapped.append(row)

    postprocess_rows(mapped)
    return mapped, header_map

def postprocess_rows(rows: List[Dict[str, Any]]) -> None:
    # Συμπλήρωσε manufacturer από model, αν λείπει
    for row in rows:
        model = (row.get("model") or "").strip()
        manufacturer = (row.get("manufacturer") or "").strip()
        if model and not manufacturer:
            parts = model.split()
            if len(parts) >= 2 and parts[0].isalpha():
                row["manufacturer"] = parts[0]
                row["model"] = " ".join(parts[1:])

    # Εξαγωγή λογιστικού αριθμού από notes -> custom_tag (και παλιό custom_tag -> notes ως ext=...)
    for row in rows:
        notes = (row.get("notes") or "").strip()
        m = _first_int_re.search(notes) if notes else None
        if m:
            extracted = m.group(1)
            prev_ct = (row.get("custom_tag") or "").strip()
            if prev_ct and prev_ct != extracted:
                sep = " | " if notes else ""
                row["notes"] = f"{notes}{sep}ext={prev_ct}"
            row["custom_tag"] = extracted

    # Παραγωγή/Διατήρηση asset_tag
    seq = ASSET_TAG_SEQ_START
    for row in rows:
        mode = (ASSET_TAG_MODE or "keep").lower()
        have = (row.get("asset_tag") or "").strip()
        base = compose_asset_from_model(row)

        if mode == "keep":
            if not have and base:
                row["asset_tag"] = base
        elif mode == "from-model":
            row["asset_tag"] = base or have or None
        elif mode == "from-model-numbered":
            numbered = base or have or "Unknown"
            row["asset_tag"] = f"{numbered} {ASSET_TAG_SEQ_PREFIX}{seq}"
            seq += 1
        else:
            if not have and base:
                row["asset_tag"] = base

# ----------------------------------------------------------------------
# DB
# ----------------------------------------------------------------------
def reflect_hardware_table(engine: Engine) -> Table:
    metadata = MetaData()
    return Table("hardware_asset", metadata, autoload_with=engine)

def _safe_param_name(col: str) -> str:
    # Απόφυγε δεσμευμένες λέξεις ως bind param names
    if col == "type":
        return "p_type"
    return col

def _update_by_id(conn, row_update: Dict[str, Any], rec_id: int) -> None:
    update_row = {k: v for k, v in row_update.items() if k not in ("id", "created_at")}
    if not update_row:
        return
    set_parts = []
    params: Dict[str, Any] = {"id": rec_id}
    for k, v in update_row.items():
        p = _safe_param_name(k)
        set_parts.append(f"{k} = :{p}")
        params[p] = v
    sql = text(f"UPDATE hardware_asset SET {', '.join(set_parts)} WHERE id = :id")
    conn.execute(sql, params)

def manual_upsert(conn, table: Table, row: Dict[str, Any]) -> str:
    """Upsert με κλειδιά serial_number -> custom_tag. Καμία επιβολή για asset_tag."""
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

    # Προληπτικός χειρισμός μόνο για custom_tag uniqueness (αν υπάρχει μοναδικός δείκτης)
    ct = valid_row.get("custom_tag")
    if ct:
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

    cols = list(valid_row.keys())
    vals = [f":{_safe_param_name(k)}" for k in cols]
    params = { _safe_param_name(k): v for k, v in valid_row.items() }

    sql = text(f"INSERT INTO hardware_asset ({', '.join(cols)}) VALUES ({', '.join(vals)})")
    conn.execute(sql, params)
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

                    ct = valid_row.get("custom_tag")
                    if ct:
                        ct_rec = conn.execute(
                            text("SELECT 1 FROM hardware_asset WHERE custom_tag::text = :c LIMIT 1"),
                            {"c": str(ct).strip()}
                        ).fetchone()
                        if ct_rec:
                            modec = (CUSTOM_UNIQUE_MODE or "nullify").lower()
                            if modec == "update":
                                print(f"[dry-run] update due to existing custom_tag='{ct}': {valid_row}")
                                updated += 1
                                continue
                            elif modec == "nullify":
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

    print(f"[✓] Ολοκληρώθηκε: inserted={inserted}, updated={updated}, skipped={skipped})")

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
    global KEY_ORDER, CUSTOM_UNIQUE_MODE, ASSET_TAG_MODE, ASSET_TAG_SEQ_START, ASSET_TAG_SEQ_PREFIX, ASSET_TAG_SEP, FIXED_CATEGORY, FIXED_TYPE

    parser = argparse.ArgumentParser(description="Import .ods/.xlsx -> hardware_asset (PostgreSQL) χωρίς asset_tag uniqueness.")
    parser.add_argument("ods_path", help="Μονοπάτι .ods/.xlsx")
    parser.add_argument("--db", dest="db_uri", default=DEFAULT_DB_URI, help="SQLAlchemy DB URI")
    parser.add_argument("--sheet", dest="sheet", default=None, help="Όνομα ή index φύλλου (default 0)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Προσομοίωση χωρίς εγγραφή")
    parser.add_argument("--print-columns", dest="print_cols", action="store_true", help="Εκτύπωση headers/δειγμάτων")
    parser.add_argument("--map", dest="map_arg", default=None, help='Overrides π.χ. --map "SERIAL NUMBER=serial_number, ΤΜΗΜΑ=location"')
    parser.add_argument("--map-file", dest="map_file", default=None, help="JSON με mapping {source: target}")
    parser.add_argument("--key-order", dest="key_order", default="serial_number,custom_tag",
                        help="Σειρά ταυτοποίησης (asset_tag αγνοείται).")
    parser.add_argument("--custom-unique-mode", dest="custom_unique_mode",
                        choices=["update", "nullify", "skip"], default="nullify",
                        help="Σύγκρουση σε custom_tag: update|nullify|skip.")
    parser.add_argument("--asset-tag-mode", dest="asset_tag_mode",
                        choices=["keep", "from-model", "from-model-numbered"], default="keep",
                        help="Παραγωγή asset_tag.")
    parser.add_argument("--asset-tag-sep", dest="asset_tag_sep", default=" ",
                        help="Διαχωριστικό μεταξύ manufacturer και model.")
    parser.add_argument("--asset-tag-seq-start", dest="asset_tag_seq_start", type=int, default=1,
                        help="Αρχικός αύξων αριθμός για numbered mode.")
    parser.add_argument("--asset-tag-seq-prefix", dest="asset_tag_seq_prefix", default="#",
                        help="Πρόθεμα αύξοντα για numbered mode.")
    parser.add_argument("--category", dest="fixed_category", default=None, help="Σταθερή Category για όλες τις εγγραφές.")
    parser.add_argument("--type", dest="fixed_type", default=None, help="Σταθερό Type για όλες τις εγγραφές.")

    args = parser.parse_args()

    KEY_ORDER = tuple(x.strip() for x in (args.key_order or "").split(",") if x.strip()) or KEY_ORDER
    CUSTOM_UNIQUE_MODE = args.custom_unique_mode
    ASSET_TAG_MODE = args.asset_tag_mode
    ASSET_TAG_SEP = args.asset_tag_sep
    ASSET_TAG_SEQ_START = int(args.asset_tag_seq_start or 1)
    ASSET_TAG_SEQ_PREFIX = args.asset_tag_seq_prefix or "#"
    FIXED_CATEGORY = args.fixed_category
    FIXED_TYPE = args.fixed_type

    ods_path = args.ods_path
    if not os.path.exists(ods_path):
        print(f"[!] Δεν βρέθηκε αρχείο: {ods_path}")
        sys.exit(1)

    print(f"[i] Διαβάζω: {ods_path}")
    df = load_ods(ods_path, args.sheet)

    if df.empty:
        print("[!] Το αρχείο δεν έχει δεδομένα.")
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
