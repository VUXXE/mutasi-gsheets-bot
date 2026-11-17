import re
from typing import List, Optional
import cv2
import numpy as np
import pytesseract
from pdf2image import convert_from_path
from pytesseract import Output

from models import DirectionType, Transaction
from extractors.common import normalize_date, parse_amount


def _preprocess_pil_image(pil_img) -> np.ndarray:
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)


def _extract_row_amounts(text: str) -> list[int]:
    """Extract numeric amounts without merging across spaces."""
    raw_nums = re.findall(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\b\d{4,}\b", text)
    results: list[int] = []
    for raw in raw_nums:
        val = parse_amount(raw)
        if val is not None:
            results.append(val)
    return results


def _parse_column_number(words: list[str]) -> Optional[int]:
    """Join OCR words inside a single numeric column (e.g. ['7', '557', '481'] -> 7557481)."""
    if not words:
        return None
    joined = "".join(words)
    return parse_amount(joined)


def _detect_line_color_direction(
    rgb_img: np.ndarray, y_min: int, y_max: int, x_min: int, x_max: int
) -> DirectionType:
    """Detect whether the amount region in the original RGB image is green (MASUK) or red (KELUAR)."""
    h, w, _ = rgb_img.shape
    y0, y1 = max(0, y_min), min(h, y_max)
    x0, x1 = max(0, x_min), min(w, x_max)
    if y1 <= y0 or x1 <= x0:
        return "UNKNOWN"

    crop = rgb_img[y0:y1, x0:x1].astype(np.int16)
    r, g, b = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]

    green_pixels = int(np.sum((g - r > 20) & (g - b > 15)))
    red_pixels = int(np.sum((r - g > 20) & (r - b > 15)))

    if green_pixels > red_pixels and green_pixels >= 8:
        return "MASUK"
    if red_pixels > green_pixels and red_pixels >= 8:
        return "KELUAR"
    return "UNKNOWN"


def _extract_page_transactions(
    pil_img,
    drive_url: str,
    initial_saldo: Optional[int],
) -> List[Transaction]:
    """
    Use Tesseract bounding boxes to separate Date+Desc, Nominal, and Saldo columns
    by X-coordinate so space-separated digits never bleed across columns.
    """
    rgb_orig = np.array(pil_img)
    gray = _preprocess_pil_image(pil_img)
    img_w = rgb_orig.shape[1]

    data = pytesseract.image_to_data(
        gray, lang="ind+eng", config="--psm 6", output_type=Output.DICT
    )

    lines_words: dict[tuple[int, int, int], list[tuple[str, int, int, int, int]]] = {}
    for idx in range(len(data["text"])):
        word = (data["text"][idx] or "").strip()
        if not word:
            continue
        key = (data["block_num"][idx], data["par_num"][idx], data["line_num"][idx])
        x = int(data["left"][idx])
        y = int(data["top"][idx])
        w = int(data["width"][idx])
        h = int(data["height"][idx])
        lines_words.setdefault(key, []).append((word, x, y, x + w, y + h))

    # Build structured line entries
    entries: list[tuple[str, str, Optional[int], Optional[int], DirectionType]] = []
    prev_saldo = initial_saldo

    for _, words in lines_words.items():
        left_words: list[str] = []
        nom_words: list[str] = []
        saldo_words: list[str] = []
        ys, y2s = [], []

        for word, x, y, x2, y2 in words:
            x_ratio = x / img_w
            ys.append(y)
            y2s.append(y2)
            if x_ratio < 0.55:
                left_words.append(word)
            elif x_ratio < 0.78:
                nom_words.append(word)
            else:
                saldo_words.append(word)

        left_text = re.sub(r"\s+", " ", " ".join(left_words)).strip()
        nom_raw = " ".join(nom_words)
        nom_val = _parse_column_number(nom_words)
        saldo_val = _parse_column_number(saldo_words)

        # Check Saldo Awal
        if prev_saldo is None and "saldo awal" in left_text.lower() and saldo_val:
            prev_saldo = saldo_val
            continue

        color_dir = "UNKNOWN"
        if nom_words or saldo_words:
            color_dir = _detect_line_color_direction(
                rgb_orig, min(ys) - 2, max(y2s) + 2, int(img_w * 0.55), int(img_w * 0.78)
            )
            if color_dir == "UNKNOWN":
                if re.search(r"\+\s*\d", nom_raw):
                    color_dir = "MASUK"
                elif re.search(r"-\s*\d", nom_raw):
                    color_dir = "KELUAR"

        entries.append((left_text, nom_raw, nom_val, saldo_val, color_dir))

    date_line_re = re.compile(
        r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s*[A-Za-z]{3,}\s+\d{2,4})\s*(.*)$"
    )

    transactions: List[Transaction] = []
    i = 0
    while i < len(entries):
        left_text, nom_raw, nom_val, saldo_val, color_dir = entries[i]
        m = date_line_re.match(left_text)
        if not m:
            i += 1
            continue

        tanggal = normalize_date(m.group(1))
        if not tanggal:
            i += 1
            continue

        desc_head = m.group(2).strip()
        extra_desc = ""
        if i + 1 < len(entries):
            next_left = entries[i + 1][0]
            if next_left and not date_line_re.match(next_left):
                if not re.search(r"(halaman|dari\s+\d+|pt bank negara)", next_left, re.IGNORECASE):
                    extra_desc = re.sub(r"\s+[!'\".|]+$", "", next_left).strip()
                    i += 1

        if nom_val is None and saldo_val is not None and prev_saldo is not None:
            nom_val = abs(prev_saldo - saldo_val)

        if not nom_val or nom_val <= 0:
            if saldo_val is not None:
                prev_saldo = saldo_val
            i += 1
            continue

        tipe: DirectionType = color_dir
        if tipe == "UNKNOWN" and saldo_val is not None and prev_saldo is not None:
            if saldo_val < prev_saldo:
                tipe = "KELUAR"
            elif saldo_val > prev_saldo:
                tipe = "MASUK"

        if saldo_val is not None:
            prev_saldo = saldo_val

        full_desc = f"{desc_head} | {extra_desc}".strip(" |") if extra_desc else desc_head

        transactions.append(
            Transaction(
                bank="BNI",
                tanggal=tanggal,
                tipe=tipe,
                nominal=nom_val,
                keterangan=full_desc or "Mutasi BNI",
                saldo=saldo_val,
                sumber="MUTASI",
                status_match="UNMATCHED",
                link_mutasi=drive_url,
            )
        )
        i += 1

    return transactions


def parse_bni_ocr_text(
    text: str,
    drive_url: str = "",
    initial_saldo: Optional[int] = None,
) -> List[Transaction]:
    """Text-only BNI parser (used by unit tests and plain-text fallbacks)."""
    transactions: List[Transaction] = []
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]
    prev_saldo: Optional[int] = initial_saldo

    date_line_re = re.compile(
        r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s*[A-Za-z]{3,}\s+\d{2,4})\s+(.+)$"
    )

    for line in lines:
        m = date_line_re.match(line)
        if not m:
            continue
        tanggal = normalize_date(m.group(1))
        if not tanggal:
            continue
        rest = m.group(2)
        amounts = _extract_row_amounts(rest)
        if not amounts:
            continue
        nominal = amounts[0]
        saldo = amounts[-1] if len(amounts) > 1 else None
        upper = rest.upper()
        if re.search(r"\b(CR|KREDIT|CREDIT|MASUK|SETOR)\b", upper):
            tipe: DirectionType = "MASUK"
        elif re.search(r"\b(DB|DEBET|DEBIT|KELUAR|TARIK|BIAYA)\b", upper):
            tipe = "KELUAR"
        elif saldo is not None and prev_saldo is not None:
            tipe = "KELUAR" if saldo < prev_saldo else ("MASUK" if saldo > prev_saldo else "UNKNOWN")
        else:
            tipe = "UNKNOWN"
        if saldo is not None:
            prev_saldo = saldo
        desc = re.sub(r"\b\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{2})?|\b\d{4,}\b", "", rest)
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
    """Convert BNI PDF pages to images and extract mutasi via column-aware OCR + color detection."""
    pages = convert_from_path(pdf_path, dpi=300)
    all_transactions: List[Transaction] = []
    last_saldo: Optional[int] = None

    for page_img in pages:
        page_txs = _extract_page_transactions(
            page_img, drive_url=drive_url, initial_saldo=last_saldo
        )
        if page_txs and page_txs[-1].saldo is not None:
            last_saldo = page_txs[-1].saldo
        all_transactions.extend(page_txs)

    return all_transactions
