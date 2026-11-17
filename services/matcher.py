from datetime import datetime
from typing import List, Optional

from models import BankType, Transaction
from services.sheets_service import SheetsService


def _parse_iso_date(val: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(val).strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _dates_within_tolerance(date_a: str, date_b: str, max_days: int = 1) -> bool:
    da = _parse_iso_date(date_a)
    db = _parse_iso_date(date_b)
    if da is None or db is None:
        return True  # Fallback if one date couldn't be parsed cleanly
    return abs((da - db).days) <= max_days


def _directions_compatible(dir_a: str, dir_b: str) -> bool:
    a = (dir_a or "UNKNOWN").upper()
    b = (dir_b or "UNKNOWN").upper()
    if a == "UNKNOWN" or b == "UNKNOWN":
        return True
    return a == b


def find_matching_row(
    rows_with_idx: list[tuple[int, dict]],
    tx: Transaction,
    target_source: str,
) -> Optional[tuple[int, dict]]:
    """Find the first UNMATCHED row of `target_source` matching nominal, direction, and date."""
    for row_num, rec in rows_with_idx:
        if str(rec.get("Status Match", "")).upper() == "MATCHED":
            continue
        if str(rec.get("Sumber", "")).upper() != target_source:
            continue

        try:
            row_nominal = int(str(rec.get("Nominal", 0)).replace(",", "").replace(".", ""))
        except ValueError:
            continue

        if row_nominal != tx.nominal:
            continue

        row_dir = str(rec.get("Tipe (MASUK/KELUAR)", "UNKNOWN"))
        if not _directions_compatible(row_dir, tx.tipe):
            continue

        row_date = str(rec.get("Tanggal", ""))
        if not _dates_within_tolerance(row_date, tx.tanggal, max_days=1):
            continue

        return row_num, rec

    return None


def match_receipt_against_sheet(sheets: SheetsService, receipt: Transaction) -> bool:
    """
    Match a receipt Transaction against existing MUTASI rows in the bank's sheet.
    Returns True if matched, False if appended as UNMATCHED.
    """
    rows = sheets.get_all_rows_with_index(receipt.bank)
    match = find_matching_row(rows, receipt, target_source="MUTASI")

    if match:
        row_num, _ = match
        sheets.mark_row_matched(
            bank=receipt.bank,
            row_number=row_num,
            link_bukti=receipt.link_bukti,
        )
        return True

    sheets.append_transactions(receipt.bank, [receipt])
    return False


def reconcile_mutasi_batch(
    sheets: SheetsService,
    bank: BankType,
    mutasi_list: List[Transaction],
) -> tuple[int, int]:
    """
    Reconcile newly extracted MUTASI rows against any existing UNMATCHED TRANSAKSI rows,
    then append all new MUTASI rows to the sheet.
    Returns (total_inserted, matched_count).
    """
    existing_rows = sheets.get_all_rows_with_index(bank)
    matched_count = 0

    for mutasi in mutasi_list:
        match = find_matching_row(existing_rows, mutasi, target_source="TRANSAKSI")
        if match:
            row_num, rec = match
            mutasi.status_match = "MATCHED"
            mutasi.link_bukti = str(rec.get("Link Bukti (Drive)", ""))
            sheets.mark_row_matched(
                bank=bank,
                row_number=row_num,
                link_mutasi=mutasi.link_mutasi,
            )
            # Mark in local cache so we don't double-match the same receipt
            rec["Status Match"] = "MATCHED"
            matched_count += 1

    inserted = sheets.append_transactions(bank, mutasi_list)
    return inserted, matched_count
