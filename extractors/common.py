import re
from datetime import datetime
from typing import Optional
import pytesseract

MONTH_MAP = {
    "jan": 1, "januari": 1, "january": 1,
    "feb": 2, "februari": 2, "february": 2,
    "mar": 3, "maret": 3, "march": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "agu": 8, "agustus": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "des": 12, "desember": 12, "dec": 12, "december": 12,
}


def configure_tesseract(tesseract_cmd: str) -> None:
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd


def parse_amount(raw: str) -> Optional[int]:
    """
    Parse Indonesian or US formatted currency string into integer IDR.
    Examples:
      'Rp 150.000,00' -> 150000
      '1,250,000.00'  -> 1250000
      '250.000'       -> 250000
      '50000'         -> 50000
    """
    if not raw:
        return None

    cleaned = re.sub(r"(?i)rp\.?", "", str(raw)).strip()
    cleaned = re.sub(r"[^\d.,]", "", cleaned)
    if not cleaned:
        return None

    # Handle decimal suffix (,00 or .00 at the end)
    if re.search(r"[.,]\d{2}$", cleaned):
        cleaned = cleaned[:-3]

    digits = re.sub(r"[.,]", "", cleaned)
    if not digits:
        return None
    try:
        val = int(digits)
        return val if val > 0 else None
    except ValueError:
        return None


def normalize_date(raw: str) -> Optional[str]:
    """Normalize common Indonesian bank date formats into YYYY-MM-DD."""
    if not raw:
        return None

    text = raw.strip()

    # DD/MM/YYYY or DD-MM-YYYY
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b", text)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # DD Mon YYYY (e.g. 17 Nov 2026, 05 Oktober 2025)
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]+)\s+(\d{2,4})\b", text)
    if m:
        day = int(m.group(1))
        mon_str = m.group(2).lower()
        year = int(m.group(3))
        if year < 100:
            year += 2000
        month = MONTH_MAP.get(mon_str)
        if month:
            try:
                return datetime(year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                pass

    return None
