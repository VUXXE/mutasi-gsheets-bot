import re
from typing import List, Optional
import cv2
import numpy as np
import pytesseract
from pdf2image import convert_from_path

from models import DirectionType, Transaction
from extractors.common import normalize_date, parse_amount


def _preprocess_pil_image(pil_img) -> np.ndarray:
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
    img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    # Enhance contrast for colored/light text (green/red numbers in BNI PDFs)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    img = clahe.apply(img)
    return img


def _extract_row_amounts(text: str) -> list[int]:
    """Extract numeric amounts (supports 800,353 / 1.380.359 / 57489)."""
    raw_nums = re.findall(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\b\d{4,}\b", text)
    results: list[int] = []
    for raw in raw_nums:
        val = parse_amount(raw)
        if val is not None:
            results.append(val)
    return results


def parse_bni_ocr_text(
    text: str,
    drive_url: str = "",
    initial_saldo: Optional[int] = None,
) -> List[Transaction]:
    """
    Parse OCR text from a BNI mutasi statement into Transaction objects.
    Supports both:
      1) Modern BNI 'Laporan Mutasi Rekening' ('01 Jan 2026 Transfer 800,353 1380,359' + next-line counterparty)
      2) Classic BNI format ('16-11-2026 SETORAN TUNAI CR 500.000,00 3.350.000,00')
    """
    transactions: List[Transaction] = []
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]

    prev_saldo: Optional[int] = initial_saldo
    # Check for "Saldo Awal 2,180,712"
    for ln in lines[:15]:
        m_awal = re.search(r"Saldo\s+Awal\s+([\d.,]+)", ln, re.IGNORECASE)
        if m_awal:
            prev_saldo = parse_amount(m_awal.group(1))
            break

    date_line_re = re.compile(
        r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s*[A-Za-z]{3,}\s+\d{2,4})\s+(.+)$"
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        m = date_line_re.match(line)
        if not m:
            i += 1
            continue

        tanggal = normalize_date(m.group(1))
        if not tanggal:
            i += 1
            continue

        rest = m.group(2)
        amounts = _extract_row_amounts(rest)
        if not amounts:
            i += 1
            continue

        # Look ahead 1 line for counterparty / time detail (e.g. "16:28:32 WIB BNI - PT ...")
        extra_desc = ""
        if i + 1 < len(lines) and not date_line_re.match(lines[i + 1]):
            next_ln = lines[i + 1]
            if not re.search(r"(halaman|dari\s+\d+|pt bank negara)", next_ln, re.IGNORECASE):
                extra_desc = re.sub(r"\s+[!'\".|]+$", "", next_ln).strip()
                i += 1

        # If OCR only captured 1 number (the ending Saldo) and dropped the nominal,
        # recover nominal from abs(prev_saldo - saldo).
        if len(amounts) == 1 and prev_saldo is not None:
            saldo = amounts[0]
            nominal = abs(prev_saldo - saldo)
            if nominal == 0:
                i += 1
                continue
        else:
            nominal = amounts[0]
            saldo = amounts[-1] if len(amounts) > 1 else None

        # Determine MASUK / KELUAR via explicit CR/DB keyword first, then via Saldo delta
        upper = rest.upper()
        tipe: DirectionType = "UNKNOWN"
        if re.search(r"\b(CR|KREDIT|CREDIT|MASUK|SETOR)\b", upper):
            tipe = "MASUK"
        elif re.search(r"\b(DB|DEBET|DEBIT|KELUAR|TARIK|BIAYA)\b", upper):
            tipe = "KELUAR"
        elif saldo is not None and prev_saldo is not None:
            if saldo < prev_saldo:
                tipe = "KELUAR"
            elif saldo > prev_saldo:
                tipe = "MASUK"

        if saldo is not None:
            prev_saldo = saldo

        desc_head = re.sub(
            r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\b\d{4,}\b", "", rest
        )
        desc_head = re.sub(r"\b(CR|DB)\b", "", desc_head, flags=re.IGNORECASE)
        desc_head = re.sub(r"\s+", " ", desc_head).strip(" -|")

        full_desc = f"{desc_head} | {extra_desc}".strip(" |") if extra_desc else desc_head

        transactions.append(
            Transaction(
                bank="BNI",
                tanggal=tanggal,
                tipe=tipe,
                nominal=nominal,
                keterangan=full_desc or "Mutasi BNI",
                saldo=saldo,
                sumber="MUTASI",
                status_match="UNMATCHED",
                link_mutasi=drive_url,
            )
        )
        i += 1

    return transactions


def extract_bni_mutasi(pdf_path: str, drive_url: str = "") -> List[Transaction]:
    """Convert BNI PDF pages to images and extract mutasi via Tesseract OCR."""
    pages = convert_from_path(pdf_path, dpi=300)
    all_transactions: List[Transaction] = []
    last_saldo: Optional[int] = None

    for page_img in pages:
        processed = _preprocess_pil_image(page_img)
        text = pytesseract.image_to_string(processed, lang="ind+eng", config="--psm 6")
        page_txs = parse_bni_ocr_text(
            text, drive_url=drive_url, initial_saldo=last_saldo
        )
        if page_txs and page_txs[-1].saldo is not None:
            last_saldo = page_txs[-1].saldo
        all_transactions.extend(page_txs)

    return all_transactions
