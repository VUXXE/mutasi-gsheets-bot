import re
from typing import List
import pdfplumber

from models import Transaction
from extractors.common import normalize_date, parse_amount


def _parse_bri_table_row(row: list[str | None], drive_url: str) -> Transaction | None:
    cells = [re.sub(r"\s+", " ", (c or "")).strip() for c in row]
    if not any(cells):
        return None

    # First cell or second cell usually contains the date
    tanggal = None
    date_idx = -1
    for i, cell in enumerate(cells[:2]):
        parsed = normalize_date(cell)
        if parsed:
            tanggal = parsed
            date_idx = i
            break
    if not tanggal:
        return None

    # Typical BRI mutasi columns:
    # [Tanggal, Uraian/Keterangan, Teller/Ref?, Debet, Kredit, Saldo]
    # or [Tanggal, Keterangan, Debet, Kredit, Saldo]
    numeric_cols: list[tuple[int, int]] = []
    text_parts: list[str] = []

    for i, cell in enumerate(cells):
        if i == date_idx or not cell:
            continue
        amt = parse_amount(cell)
        # Only treat as numeric column if cell looks purely like a number/amount
        if amt is not None and re.fullmatch(r"[\d.,\sRp-]+", cell, re.IGNORECASE):
            numeric_cols.append((i, amt))
        else:
            text_parts.append(cell)

    if not numeric_cols:
        return None

    keterangan = " | ".join(text_parts) if text_parts else "Mutasi BRI"

    # Heuristic for Debet / Kredit / Saldo
    tipe = "UNKNOWN"
    nominal = 0
    saldo = None

    if len(numeric_cols) >= 3:
        # [Debet, Kredit, Saldo] - one of Debet/Kredit is 0 or empty
        debet_val = numeric_cols[-3][1]
        kredit_val = numeric_cols[-2][1]
        saldo = numeric_cols[-1][1]
        if debet_val > 0 and kredit_val == 0:
            tipe, nominal = "KELUAR", debet_val
        elif kredit_val > 0:
            tipe, nominal = "MASUK", kredit_val
        else:
            tipe, nominal = "KELUAR", debet_val
    elif len(numeric_cols) == 2:
        # Either [Nominal, Saldo] with DB/CR keyword in keterangan, or [Debet/Kredit, Saldo]
        nominal = numeric_cols[0][1]
        saldo = numeric_cols[1][1]
        desc_upper = keterangan.upper()
        if any(k in desc_upper for k in ("CR", "KREDIT", "MASUK", "SETOR")):
            tipe = "MASUK"
        elif any(k in desc_upper for k in ("DB", "DEBET", "KELUAR", "TARIK", "TRSF")):
            tipe = "KELUAR"
    else:
        nominal = numeric_cols[0][1]

    if nominal <= 0:
        return None

    return Transaction(
        bank="BRI",
        tanggal=tanggal,
        tipe=tipe,
        nominal=nominal,
        keterangan=keterangan,
        saldo=saldo,
        sumber="MUTASI",
        status_match="UNMATCHED",
        link_mutasi=drive_url,
    )


def _parse_bri_text_lines(text: str, drive_url: str) -> List[Transaction]:
    txs: List[Transaction] = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue

        date_match = re.match(r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(.+)$", line)
        if not date_match:
            continue

        tanggal = normalize_date(date_match.group(1))
        if not tanggal:
            continue

        rest = date_match.group(2)
        amounts = re.findall(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?\b", rest)
        if not amounts:
            continue

        parsed_amounts = [a for a in (parse_amount(x) for x in amounts) if a]
        if not parsed_amounts:
            continue

        nominal = parsed_amounts[0]
        saldo = parsed_amounts[-1] if len(parsed_amounts) > 1 else None

        desc = rest
        for raw_amt in amounts:
            desc = desc.replace(raw_amt, "")
        desc = re.sub(r"\s+", " ", desc).strip(" -|")

        desc_upper = desc.upper()
        if any(k in desc_upper for k in ("CR", "KREDIT", "MASUK", "SETOR")):
            tipe = "MASUK"
        elif any(k in desc_upper for k in ("DB", "DEBET", "KELUAR", "TARIK", "TRSF", "BIAYA")):
            tipe = "KELUAR"
        else:
            tipe = "UNKNOWN"

        txs.append(
            Transaction(
                bank="BRI",
                tanggal=tanggal,
                tipe=tipe,
                nominal=nominal,
                keterangan=desc or "Mutasi BRI",
                saldo=saldo,
                sumber="MUTASI",
                status_match="UNMATCHED",
                link_mutasi=drive_url,
            )
        )
    return txs


def extract_bri_mutasi(pdf_path: str, drive_url: str = "") -> List[Transaction]:
    """Extract BRI mutasi transactions from a text-based PDF using pdfplumber."""
    transactions: List[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_txs: List[Transaction] = []
            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    tx = _parse_bri_table_row(row, drive_url)
                    if tx:
                        page_txs.append(tx)

            if not page_txs:
                text = page.extract_text() or ""
                page_txs = _parse_bri_text_lines(text, drive_url)

            transactions.extend(page_txs)

    return transactions
