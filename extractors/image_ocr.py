import re
from datetime import datetime
from typing import Optional, Tuple
import cv2
import pytesseract

from models import BankType, DirectionType, Transaction
from extractors.common import normalize_date, parse_amount

TRANSACTION_KEYWORDS = {
    "transfer", "berhasil", "sukses", "nominal", "jumlah", "total",
    "rekening", "saldo", "referensi", "no. ref", "ref", "qris",
    "pembayaran", "pembelian", "top up", "topup", "biaya admin",
    "penerima", "pengirim", "bni", "bri", "brimo", "wondr", "briva",
    "transaksi", "mutasi",
}

BNI_KEYWORDS = {"bni", "wondr", "bni mobile", "taplus"}
BRI_KEYWORDS = {"bri", "brimo", "briva", "simpedes", "britama"}

MASUK_KEYWORDS = {"dana masuk", "uang masuk", "diterima", "setor tunai", "kredit"}
KELUAR_KEYWORDS = {
    "transfer berhasil", "kirim", "pembayaran", "pembelian",
    "tarik tunai", "debet", "biaya", "bayar",
}


def _preprocess_receipt(image_path: str):
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Upscale small screenshots for better OCR
    h, w = gray.shape
    if max(h, w) < 1200:
        gray = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def _run_ocr(image_path: str) -> str:
    processed = _preprocess_receipt(image_path)
    try:
        return pytesseract.image_to_string(processed, lang="ind+eng", config="--psm 6")
    except pytesseract.TesseractError:
        return pytesseract.image_to_string(processed, lang="eng", config="--psm 6")


def classify_and_parse_receipt(
    raw_text: str,
    drive_url: str = "",
    hint_text: str = "",
) -> Tuple[Optional[Transaction], Optional[str]]:
    """
    Classify OCR text from a photo.
    Returns:
      (Transaction, None) if valid BNI/BRI transaction
      (None, reason_string) if it should go to ANOMALI
    """
    combined = f"{raw_text}\n{hint_text}".lower()

    matched_keywords = [kw for kw in TRANSACTION_KEYWORDS if kw in combined]
    if len(matched_keywords) < 2 and "rp" not in combined:
        return None, "Foto bukan bukti transaksi (keyword transaksi tidak ditemukan)"

    # Extract nominal: prioritize explicit "Rp ..." or "Nominal / Total ..." lines
    nominal = None
    rp_matches = re.findall(
        r"(?:rp\.?\s*|nominal\s*[:\-]?\s*|total\s*[:\-]?\s*)(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\d{4,})",
        raw_text,
        flags=re.IGNORECASE,
    )
    if rp_matches:
        parsed_vals = [v for v in (parse_amount(m) for m in rp_matches) if v and v >= 1000]
        if parsed_vals:
            nominal = max(parsed_vals)

    if nominal is None:
        return None, "Nominal transaksi tidak ditemukan pada foto"

    # Determine bank
    bank: BankType | None = None
    if any(k in combined for k in BNI_KEYWORDS):
        bank = "BNI"
    elif any(k in combined for k in BRI_KEYWORDS):
        bank = "BRI"

    if bank is None:
        return None, "Bank (BNI/BRI) tidak teridentifikasi pada foto transaksi"

    # Determine direction (MASUK / KELUAR)
    tipe: DirectionType = "UNKNOWN"
    if any(k in combined for k in MASUK_KEYWORDS):
        tipe = "MASUK"
    elif any(k in combined for k in KELUAR_KEYWORDS):
        tipe = "KELUAR"

    # Extract date or fallback to today
    tanggal = None
    for line in raw_text.splitlines():
        tanggal = normalize_date(line)
        if tanggal:
            break
    if not tanggal:
        tanggal = datetime.now().strftime("%Y-%m-%d")

    summary_lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    keterangan = " | ".join(summary_lines[:4])[:200] if summary_lines else f"Bukti {bank}"

    tx = Transaction(
        bank=bank,
        tanggal=tanggal,
        tipe=tipe,
        nominal=nominal,
        keterangan=keterangan,
        sumber="TRANSAKSI",
        status_match="UNMATCHED",
        link_bukti=drive_url,
    )
    return tx, None


def extract_receipt_image(
    image_path: str,
    drive_url: str = "",
    hint_text: str = "",
) -> Tuple[Optional[Transaction], Optional[str], str]:
    """Run OCR on an image and classify it as BNI/BRI Transaction or ANOMALI."""
    raw_text = _run_ocr(image_path)
    tx, anomaly_reason = classify_and_parse_receipt(
        raw_text=raw_text,
        drive_url=drive_url,
        hint_text=hint_text,
    )
    return tx, anomaly_reason, raw_text
