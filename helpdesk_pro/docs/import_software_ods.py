# import_software_ods.py
# -*- coding: utf-8 -*-
"""
Import .ods σε PostgreSQL πίνακα software_asset με:
- Auto-mapping (EL/EN) + χειροκίνητα overrides (--map/--map-file)
- Timezone-aware timestamps
- Ενσωμάτωση «ΟΝΟΜ/ΜΟ ΧΡΗΣΤΗ» στα notes ως user=<...> (αν υπάρχει)
- Παραγωγή asset_tag από Vendor + ProductName + Version, με σειριακή αρίθμηση στο ΤΕΛΟΣ: "<Vendor> <ProductName> <Version> #<n>"
  ρυθμίσιμη με --asset-tag-seq-start και --asset-tag-seq-prefix
- Χειρισμό UNIQUE για license identifiers (license_key, entitlement_id, sku) με --license-unique-mode (default: nullify)
- Χειροκίνητο upsert χωρίς ON CONFLICT, key order: license_key → entitlement_id → sku → product_name+vendor+version → asset_tag
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

SW_COLUMNS = {
    "asset_tag",
    "product_name", "vendor", "version", "edition", "category",
    "license_key", "license_type", "entitlement_id", "sku",
    "subscription_term", "seats_purchased", "seats_in_use",
    "compliance_status", "cost_center", "invoice_number", "contract_id",
    "purchase_date", "expiry_date", "maintenance_end",
    "support_vendor", "support_contract",
    "assigned_to", "assigned_on",
    "device_hostname", "operating_system", "install_path",
    "status", "notes", "created_at", "updated_at"
}

RAW_SYNONYMS = {
    # EN
    "asset": "asset_tag", "asset tag": "asset_tag", "asset id": "asset_tag", "tag": "asset_tag",
    "product": "product_name", "product name": "product_name", "software": "product_name", "title": "product_name",
    "vendor": "vendor", "manufacturer": "vendor", "publisher": "vendor", "maker": "vendor",
    "version": "version", "ver": "version", "build": "version",
    "edition": "edition",
    "category": "category", "type": "category", "class": "category",
    "license": "license_key", "license key": "license_key", "key": "license_key", "serial": "license_key",
    "license type": "license_type", "licensing": "license_type",
    "entitlement": "entitlement_id", "entitlement id": "entitlement_id",
    "sku": "sku", "part number": "sku",
    "subscription term": "subscription_term", "term": "subscription_term",
    "seats": "seats_purchased", "seats purchased": "seats_purchased", "purchased seats": "seats_purchased",
    "seats in use": "seats_in_use", "used seats": "seats_in_use",
    "compliance": "compliance_status", "compliance status": "compliance_status",
    "cost center": "cost_center", "cost centre": "cost_center",
    "invoice": "invoice_number", "invoice number": "invoice_number",
    "contract": "contract_id", "contract id": "contract_id",
    "purchase date": "purchase_date", "bought": "purchase_date",
    "expiry date": "expiry_date", "expiration": "expiry_date", "expires": "expiry_date",
    "maintenance end": "maintenance_end", "support end": "maintenance_end",
    "support vendor": "support_vendor", "support contract": "support_contract",
    "assigned to": "assigned_to", "assignee": "assigned_to",
    "assigned on": "assigned_on", "assignment date": "assigned_on",
    "device hostname": "device_hostname", "hostname": "device_hostname",
    "os": "operating_system", "operating system": "operating_system",
    "install path": "install_path", "path": "install_path",
    "status": "status",
    "notes": "notes", "comment": "notes", "comments": "notes",

    # EL
    "κωδικος παγιου": "asset_tag", "κωδικός παγίου": "asset_tag",
    "προιον": "product_name", "προϊόν": "product_name", "λογισμικο": "product_name", "λογισμικό": "product_name", "τιτλος": "product_name", "τίτλος": "product_name",
    "προμηθευτης": "vendor", "προμηθευτής": "vendor", "κατασκευαστης": "vendor", "κατασκευαστής": "vendor", "εκδοτης": "vendor", "εκδότης": "vendor",
    "εκδοση": "version", "έκδοση": "version", "build": "version",
    "ετινιον": "edition", "εκδοση/edition": "edition", "έκδοση/edition": "edition",
    "κατηγορια": "category", "κατηγορία": "category", "τυπος": "category", "τύπος": "category",
    "κλειδι αδειας": "license_key", "κλειδί άδειας": "license_key", "αδεια": "license_key", "άδεια": "license_key", "σειριακος": "license_key", "σειριακός": "license_key",
    "τυπος αδειας": "license_type", "τύπος άδειας": "license_type",
    "entitlement": "entitlement_id", "entitlement id": "entitlement_id", "αναθεση δικαιωματος": "entitlement_id", "ανάθεση δικαιώματος": "entitlement_id",
    "sku": "sku", "κωδικος προιοντος": "sku", "κωδικός προϊόντος": "sku",
    "διαρκεια συνδρομης": "subscription_term", "διάρκεια συνδρομής": "subscription_term",
    "καθισματα": "seats_purchased", "καθίσματα": "seats_purchased", "θεσεις": "seats_purchased", "θέσεις": "seats_purchased",
    "σε χρηση": "seats_in_use", "σε χρήση": "seats_in_use",
    "συμμορφωση": "compliance_status", "συμμόρφωση": "compliance_status",
    "κεντρο κοστους": "cost_center", "κέντρο κόστους": "cost_center",
    "τιμολογιο": "invoice_number", "τιμολόγιο": "invoice_number",
    "συμβολαιο": "contract_id", "συμβόλαιο": "contract_id",
    "ημ/νια αγορας": "purchase_date", "ημ/νία αγοράς": "purchase_date", "ημερομηνια αγορας": "purchase_date", "ημερομηνία αγοράς": "purchase_date",
    "ημ/νια ληξης": "expiry_date", "ημ/νία λήξης": "expiry_date", "ημερομηνια ληξης": "expiry_date", "ημερομηνία λήξης": "expiry_date",
    "ληξη συντηρησης": "maintenance_end", "λήξη συντήρησης": "maintenance_end",
    "προμηθευτης υποστηριξης": "support_vendor",
    "συμβολαιο υποστηριξης": "support_contract",
    "υπευθυνος": "assigned_to",
    "ημερομηνια αναθεσης": "assigned_on", "ημερομηνία ανάθεσης": "assigned_on",
    "ονομα υπολογιστη": "device_hostname", "όνομα υπολογιστή": "device_hostname",
    "λειτουργικο": "operating_system", "λειτουργικό": "operating_system",
    "μονοπατι εγκαταστασης": "install_path", "μονοπάτι εγκατάστασης": "install_path",
    "σημειωσεις": "notes", "σημειώσεις": "notes",
}

DATE_COLUMNS = {"purchase_date", "expiry_date", "maintenance_end", "assigned_on", "created_at", "updated_at"}
KEY_COLUMNS_AS_TEXT = {
    "asset_tag", "product_name", "vendor", "version", "edition", "category",
    "license_key", "license_type", "entitlement_id", "sku",
    "subscription_term", "compliance_status", "cost_center", "invoice_number", "contract_id",
    "support_vendor", "support_contract", "assigned_to",
    "device_hostname", "operating_system", "install_path", "status", "notes"
}

# Key order: single columns + composite "product_name_vendor_version"
KEY_ORDER = ("license_key", "entitlement_id", "sku", "product_name_vendor_version", "asset_tag")

# unique handling for license identifiers
LICENSE_UNIQUE_MODE = "nullify"  # update | nullify | skip
LICENSE_UNIQUE_COLS = ("license_key", "entitlement_id", "sku")

ASSET_TAG_SEP = " "
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
    for col in SW_COLUMNS:
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
# Value coercion / dates
# ----------------------------------------------------------------------
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
    if col in {"seats_purchased", "seats_in_use"}:
        s = str(val).strip()
        return int(s) if s.isdigit() else None
    return val

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
        if tgt not in SW_COLUMNS:
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
    targets = {"ονομ μο χρηστη", "ονομα χρηστη", "ονομα χρηστης", "χρηστης", "user", "user name", "username", "user full name"}
    best = (0.0, None)
    for c in df.columns:
        cn = normalise_header(str(c))
        if cn in targets:
            return c
        score = max(SequenceMatcher(None, cn, t).ratio() for t in targets)
        if score > best[0]:
            best = (score, c)
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
        print("[!] Δεν έγινε ταίριασμα καμίας στήλης. Έλεγξε τα headers ή --print-columns/--map.")
        return [], {}

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

def compose_asset_base(row: Dict[str, Any]) -> Optional[str]:
    vendor = (row.get("vendor") or "").strip()
    prod = (row.get("product_name") or "").strip()
    ver = (row.get("version") or "").strip()
    base = " ".join(x for x in [vendor, prod, ver] if x)
    return base or None

def postprocess_rows(rows: List[Dict[str, Any]]) -> None:
    # Παραγωγή asset_tag βάσης και αρίθμηση στο ΤΕΛΟΣ
    for row in rows:
        base = compose_asset_base(row) or "Unknown"
        row["asset_tag"] = base

    n = ASSET_TAG_SEQ_START
    for row in rows:
        base = (row.get("asset_tag") or "Unknown").strip()
        row["asset_tag"] = f"{base} {ASSET_TAG_SEQ_PREFIX}{n}"
        n += 1

# ----------------------------------------------------------------------
# DB utilities
# ----------------------------------------------------------------------
def reflect_software_table(engine: Engine) -> Table:
    metadata = MetaData()
    return Table("software_asset", metadata, autoload_with=engine)

def _update_by_id(conn, row_update: Dict[str, Any], rec_id: int) -> None:
    update_row = {k: v for k, v in row_update.items() if k not in ("id", "created_at")}
    if not update_row:
        return
    set_clause = ", ".join([f"{k} = :{k}" for k in update_row.keys()])
    params = dict(update_row)
    params["id"] = rec_id
    conn.execute(text(f"UPDATE software_asset SET {set_clause} WHERE id = :id"), params)

def _select_by_composite_pvv(conn, row: Dict[str, Any]) -> Optional[int]:
    pn = (row.get("product_name") or "").strip()
    vd = (row.get("vendor") or "").strip()
    ver = (row.get("version") or "").strip()
    if not (pn and vd and ver):
        return None
    rec = conn.execute(
        text("""SELECT id FROM software_asset
                WHERE lower(product_name)=lower(:pn)
                  AND lower(vendor)=lower(:vd)
                  AND lower(version)=lower(:ver)
                LIMIT 1"""),
        {"pn": pn, "vd": vd, "ver": ver}
    ).fetchone()
    return rec[0] if rec else None

def _select_by_single(conn, col: str, val: str) -> Optional[int]:
    if not val:
        return None
    rec = conn.execute(
        text(f"SELECT id FROM software_asset WHERE {col}::text = :v LIMIT 1"),
        {"v": val}
    ).fetchone()
    return rec[0] if rec else None

def choose_conflict_key(row: Dict[str, Any]) -> Optional[str]:
    for key in KEY_ORDER:
        if key == "product_name_vendor_version":
            if (row.get("product_name") and row.get("vendor") and row.get("version")):
                return key
        else:
            v = row.get(key)
            if v and str(v).strip():
                return key
    return None

def manual_upsert(conn, table: Table, row: Dict[str, Any]) -> str:
    """Upsert: license_key → entitlement_id → sku → (product_name+vendor+version) → asset_tag"""
    valid_row = {k: v for k, v in row.items() if k in table.c}
    conflict_key = choose_conflict_key(valid_row)
    if not conflict_key:
        return "skip"

    rec_id = None
    if conflict_key == "product_name_vendor_version":
        rec_id = _select_by_composite_pvv(conn, valid_row)
    else:
        rec_id = _select_by_single(conn, conflict_key, str(valid_row.get(conflict_key)).strip())

    if rec_id:
        _update_by_id(conn, valid_row, rec_id)
        return "update"

    # Προληπτικός χειρισμός για license identifiers που συχνά έχουν unique
    for col in LICENSE_UNIQUE_COLS:
        v = (valid_row.get(col) or "").strip() if isinstance(valid_row.get(col), str) else valid_row.get(col)
        if v:
            existing_id = _select_by_single(conn, col, str(v).strip())
            if existing_id:
                modec = (LICENSE_UNIQUE_MODE or "nullify").lower()
                if modec == "update":
                    _update_by_id(conn, valid_row, existing_id)
                    return "update"
                elif modec == "nullify":
                    n = (valid_row.get("notes") or "")
                    sep = " | " if n else ""
                    valid_row["notes"] = f"{n}{sep}{col}={v}"
                    valid_row[col] = None
                elif modec == "skip":
                    return "skip"

    cols = ", ".join(valid_row.keys())
    vals = ", ".join([f":{k}" for k in valid_row.keys()])
    conn.execute(text(f"INSERT INTO software_asset ({cols}) VALUES ({vals})"), valid_row)
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
                    key = choose_conflict_key(valid_row)
                    exists = False
                    if key == "product_name_vendor_version":
                        rid = _select_by_composite_pvv(conn, valid_row)
                        exists = rid is not None
                        val_repr = f"{valid_row.get('product_name')}|{valid_row.get('vendor')}|{valid_row.get('version')}"
                    else:
                        v = str(valid_row.get(key)).strip() if key else None
                        exists = _select_by_single(conn, key, v) is not None
                        val_repr = v

                    if exists:
                        print(f"[dry-run] update on {key}='{val_repr}': {valid_row}")
                        updated += 1
                        continue

                    # license collisions
                    handled = False
                    for col in LICENSE_UNIQUE_COLS:
                        cv = (valid_row.get(col) or "").strip() if isinstance(valid_row.get(col), str) else valid_row.get(col)
                        if cv:
                            if _select_by_single(conn, col, str(cv).strip()) is not None:
                                modec = (LICENSE_UNIQUE_MODE or "nullify").lower()
                                if modec == "update":
                                    print(f"[dry-run] update due to existing {col}='{cv}': {valid_row}")
                                    updated += 1
                                    handled = True
                                    break
                                elif modec == "nullify":
                                    vr = dict(valid_row)
                                    n = (vr.get("notes") or "")
                                    sep = " | " if n else ""
                                    vr["notes"] = f"{n}{sep}{col}={cv}"
                                    vr[col] = None
                                    print(f"[dry-run] insert(nullify {col}->notes) on {key}='{val_repr}': {vr}")
                                    inserted += 1
                                    handled = True
                                    break
                                else:
                                    print(f"[dry-run] skip due to existing {col}='{cv}': {valid_row}")
                                    skipped += 1
                                    handled = True
                                    break
                    if handled:
                        continue

                    print(f"[dry-run] insert on {key}='{val_repr}': {valid_row}")
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
    global KEY_ORDER, LICENSE_UNIQUE_MODE, ASSET_TAG_SEQ_START, ASSET_TAG_SEQ_PREFIX, ASSET_TAG_SEP

    parser = argparse.ArgumentParser(
        description="Import .ods σε software_asset (PostgreSQL) με χειροκίνητο upsert."
    )
    parser.add_argument("ods_path", help="Μονοπάτι στο αρχείο .ods")
    parser.add_argument("--db", dest="db_uri", default=DEFAULT_DB_URI, help="SQLAlchemy DB URI")
    parser.add_argument("--sheet", dest="sheet", default=None, help="Όνομα ή index φύλλου (προεπιλογή: 0)")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", help="Χωρίς εγγραφή στη ΒΔ, μόνο προεπισκόπηση")
    parser.add_argument("--print-columns", dest="print_cols", action="store_true", help="Εκτύπωση headers/δειγμάτων και έξοδος")
    parser.add_argument("--map", dest="map_arg", default=None, help='Manual overrides, π.χ. --map "Vendor=vendor, Product=product_name"')
    parser.add_argument("--map-file", dest="map_file", default=None, help="JSON με manual mapping {source: target, ...}")
    parser.add_argument("--key-order", dest="key_order",
                        default="license_key,entitlement_id,sku,product_name_vendor_version,asset_tag",
                        help="Σειρά προτεραιότητας κλειδιών ταυτοποίησης (comma-sep). Περιλαμβάνει το composite 'product_name_vendor_version'.")
    parser.add_argument("--license-unique-mode", dest="license_unique_mode",
                        choices=["update", "nullify", "skip"], default="nullify",
                        help="Αν υπάρξει σύγκρουση σε license_key/entitlement_id/SKU: update, nullify (default), ή skip.")
    parser.add_argument("--asset-tag-sep", dest="asset_tag_sep", default=" ",
                        help="Διαχωριστικό μεταξύ vendor, product και version.")
    parser.add_argument("--asset-tag-seq-start", dest="asset_tag_seq_start", type=int, default=1,
                        help="Αρχικός αύξων αριθμός για το asset_tag (default: 1).")
    parser.add_argument("--asset-tag-seq-prefix", dest="asset_tag_seq_prefix", default="#",
                        help="Πρόθεμα αύξοντα (default: '#').")

    args = parser.parse_args()

    KEY_ORDER = tuple(x.strip() for x in (args.key_order or "").split(",") if x.strip()) or KEY_ORDER
    LICENSE_UNIQUE_MODE = args.license_unique_mode
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
        table = reflect_software_table(engine)
    except Exception as e:
        print(f"[!] Αποτυχία ανάγνωσης σχήματος πίνακα 'software_asset': {e}")
        sys.exit(2)

    if rows:
        print("\n[map] Χαρτογράφηση που θα χρησιμοποιηθεί:")
        for src, tgt in header_map.items():
            print(f"  '{src}'  →  {tgt}")

    upsert_rows(engine, table, rows, dry_run=args.dry_run)

if __name__ == "__main__":
    main()
