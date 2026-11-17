import re
from typing import List
import cv2
import numpy as np
import pytesseract
from pdf2image import convert_from_path

from models import Transaction
from extractors.common import normalize_date, parse_amount


def _preprocess_pil_image(pil_img) -> np.ndarray:
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
    img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def parse_bni_ocr_text(text: str, drive_url: str = "") -> List[Transaction]:
    """Parse OCR text from a BNI mutasi statement into Transaction objects."""
    transactions: List[Transaction] = []

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue

        # Look for date at start of line (e.g., 17/11/2026 or 17-11-2026)
        date_match = re.match(r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\s+(.+)$", line)
        if not date_match:
            continue

        tanggal = normalize_date(date_match.group(1))
        if not tanggal:
            continue

        rest = date_match.group(2)

        # Find formatted amounts like 150.000,00 or 1,500,000.00 or 150.000
        amounts = re.findall(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?\b", rest)
        parsed_amounts = [a for a in (parse_amount(x) for x in amounts) if a]
        if not parsed_amounts:
            continue

        nominal = parsed_amounts[0]
        saldo = parsed_amounts[-1] if len(parsed_amounts) > 1 else None

        # Detect DB / CR or Kredit / Debet
        upper = rest.upper()
        if re.search(r"\b(CR|KREDIT|CREDIT|MASUK|SETOR)\b", upper):
            tipe = "MASUK"
        elif re.search(r"\b(DB|DEBET|DEBIT|KELUAR|TARIK|TRSF|BIAYA)\b", upper):
            tipe = "KELUAR"
        else:
            tipe = "UNKNOWN"

        desc = rest
        for raw_amt in amounts:
            desc = desc.replace(raw_amt, "")
        desc = re.sub(r"\b(CR|DB)\b", "", desc, flags=re.IGNORECASE)
        desc = re.sub(r"\s+", " ", desc).strip(" -|")

        transactions.append(
            Transaction(
                bank="BNI",
                tanggal=tanggal,
                tipe=tipe,
                nominal=nominal,
                keterangan=desc or "Mutasi BNI",
                saldo=saldo,
                sumber="MUTASI",
                status_match="UNMATCHED",
                link_mutasi=drive_url,
            )
        )

    return transactions


def extract_bni_mutasi(pdf_path: str, drive_url: str = "") -> List[Transaction]:
    """Convert BNI PDF pages to images and extract mutasi via Tesseract OCR."""
    pages = convert_from_path(pdf_path, dpi=300)
    all_transactions: List[Transaction] = []

    for page_img in pages:
        processed = _preprocess_pil_image(page_img)
        text = pytesseract.image_to_string(processed, lang="ind+eng", config="--psm 6")
        all_transactions.extend(parse_bni_ocr_text(text, drive_url=drive_url))

    return all_transactions
