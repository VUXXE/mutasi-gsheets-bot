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
    img = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2GRAY)
    img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(img)


def _extract_row_amounts(text: str) -> list[int]:
    """Extract numeric amounts (supports 63,000 / 63 000 / 2 557 481 / 57489)."""
    raw_nums = re.findall(
        r"\b\d{1,3}(?:[., ]\d{3})+(?:[.,]\d{2})?|\b\d{4,}\b", text
    )
    results: list[int] = []
    for raw in raw_nums:
        val = parse_amount(raw)
        if val is not None:
            results.append(val)
    return results


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


def _extract_lines_with_color(pil_img) -> tuple[str, dict[int, DirectionType]]:
    """
    Run Tesseract with bounding boxes on the 1.5x preprocessed image,
    and map each reconstructed line index to its detected RGB color direction.
    """
    rgb_orig = np.array(pil_img)
    processed = _preprocess_pil_image(pil_img)
    scale = 1.5

    data = pytesseract.image_to_data(
        processed, lang="ind+eng", config="--psm 6", output_type=Output.DICT
    )

    lines_words: dict[tuple[int, int, int], list[tuple[str, int, int, int, int]]] = {}
    n = len(data["text"])
    for idx in range(n):
        word = (data["text"][idx] or "").strip()
        if not word:
            continue
        key = (data["block_num"][idx], data["par_num"][idx], data["line_num"][idx])
        x = int(data["left"][idx] / scale)
        y = int(data["top"][idx] / scale)
        w = int(data["width"][idx] / scale)
        h = int(data["height"][idx] / scale)
        lines_words.setdefault(key, []).append((word, x, y, x + w, y + h))

    reconstructed_lines: list[str] = []
    line_colors: dict[int, DirectionType] = {}

    for line_idx, (_, words) in enumerate(lines_words.items()):
        line_text = " ".join(w[0] for w in words)
        reconstructed_lines.append(line_text)
        # Nominal is in the middle-right area of the line (exclude far-left date & far-right saldo)
        if len(words) >= 3:
            ys = [w[2] for w in words]
            y2s = [w[4] for w in words]
            img_w = rgb_orig.shape[1]
            # Check middle-right region (45% to 80% of page width) where +/- nominal sits
            color_dir = _detect_line_color_direction(
                rgb_orig, min(ys) - 2, max(y2s) + 2, int(img_w * 0.45), int(img_w * 0.80)
            )
            if color_dir != "UNKNOWN":
                line_colors[line_idx] = color_dir

    return "\n".join(reconstructed_lines), line_colors


def parse_bni_ocr_text(
    text: str,
    drive_url: str = "",
    initial_saldo: Optional[int] = None,
    line_colors: Optional[dict[int, DirectionType]] = None,
) -> List[Transaction]:
    """
    Parse OCR text from a BNI mutasi statement into Transaction objects.
    Supports both:
      1) Modern BNI 'Laporan Mutasi Rekening' ('01 Jan 2026 Transfer 800,353 1,380,359' + next-line counterparty)
      2) Classic BNI format ('16-11-2026 SETORAN TUNAI CR 500.000,00 3.350.000,00')
    """
    transactions: List[Transaction] = []
    raw_lines = text.splitlines()
    lines: list[str] = []
    orig_indices: list[int] = []
    for idx, ln in enumerate(raw_lines):
        cleaned = re.sub(r"\s+", " ", ln).strip()
        if cleaned:
            lines.append(cleaned)
            orig_indices.append(idx)

    prev_saldo: Optional[int] = initial_saldo
    for ln in lines[:15]:
        m_awal = re.search(r"Saldo\s+Awal\s+([\d., ]+)", ln, re.IGNORECASE)
        if m_awal:
            prev_saldo = parse_amount(m_awal.group(1))
            break

    date_line_re = re.compile(
        r"^(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s*[A-Za-z]{3,}\s+\d{2,4})\s+(.+)$"
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        orig_idx = orig_indices[i]
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

        extra_desc = ""
        if i + 1 < len(lines) and not date_line_re.match(lines[i + 1]):
            next_ln = lines[i + 1]
            if not re.search(r"(halaman|dari\s+\d+|pt bank negara)", next_ln, re.IGNORECASE):
                extra_desc = re.sub(r"\s+[!'\".|]+$", "", next_ln).strip()
                i += 1

        if len(amounts) == 1 and prev_saldo is not None:
            saldo = amounts[0]
            nominal = abs(prev_saldo - saldo)
            if nominal == 0:
                i += 1
                continue
        else:
            nominal = amounts[0]
            saldo = amounts[-1] if len(amounts) > 1 else None

        # Priority 1: explicit CR/DB or +/- sign
        # Priority 2: green/red pixel color from original PDF image
        # Priority 3: Saldo delta vs previous row
        upper = rest.upper()
        tipe: DirectionType = "UNKNOWN"
        if re.search(r"\b(CR|KREDIT|CREDIT|MASUK|SETOR)\b", upper) or re.search(r"\+\s*\d", rest):
            tipe = "MASUK"
        elif re.search(r"\b(DB|DEBET|DEBIT|KELUAR|TARIK|BIAYA)\b", upper) or re.search(r"(?<!\d)-\s*\d", rest):
            tipe = "KELUAR"
        elif line_colors and orig_idx in line_colors:
            tipe = line_colors[orig_idx]
        elif saldo is not None and prev_saldo is not None:
            if saldo < prev_saldo:
                tipe = "KELUAR"
            elif saldo > prev_saldo:
                tipe = "MASUK"

        if saldo is not None:
            prev_saldo = saldo

        desc_head = re.sub(
            r"\b\d{1,3}(?:[., ]\d{3})+(?:[.,]\d{2})?|\b\d{4,}\b", "", rest
        )
        desc_head = re.sub(r"\b(CR|DB)\b", "", desc_head, flags=re.IGNORECASE)
        desc_head = re.sub(r"\s+", " ", desc_head).strip(" -|+")

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
    """Convert BNI PDF pages to images and extract mutasi via Tesseract OCR + color detection."""
    pages = convert_from_path(pdf_path, dpi=300)
    all_transactions: List[Transaction] = []
    last_saldo: Optional[int] = None

    for page_img in pages:
        text, line_colors = _extract_lines_with_color(page_img)
        page_txs = parse_bni_ocr_text(
            text,
            drive_url=drive_url,
            initial_saldo=last_saldo,
            line_colors=line_colors,
        )
        if page_txs and page_txs[-1].saldo is not None:
            last_saldo = page_txs[-1].saldo
        all_transactions.extend(page_txs)

    return all_transactions
