from extractors.bni_ocr import parse_bni_ocr_text
from extractors.bri_pdf import _parse_bri_text_lines
from extractors.common import normalize_date, parse_amount
from extractors.image_ocr import classify_and_parse_receipt
from models import Transaction
from services.matcher import find_matching_row


def test_parse_amount_and_date():
    assert parse_amount("Rp 150.000,00") == 150000
    assert parse_amount("1,250,000.00") == 1250000
    assert parse_amount("250.000") == 250000
    assert normalize_date("17/11/2026") == "2026-11-17"
    assert normalize_date("05 Oktober 2025") == "2025-10-05"


def test_parse_bri_text_lines():
    sample = "17/11/2026 TRSF E-BANKING DB TOKO MAJU 150.000,00 2.850.000,00"
    txs = _parse_bri_text_lines(sample, drive_url="https://drive.google.com/bri")
    assert len(txs) == 1
    assert txs[0].bank == "BRI"
    assert txs[0].tanggal == "2026-11-17"
    assert txs[0].tipe == "KELUAR"
    assert txs[0].nominal == 150000
    assert txs[0].saldo == 2850000


def test_parse_bni_ocr_text():
    sample = "16-11-2026 SETORAN TUNAI CR 500.000,00 3.350.000,00"
    txs = parse_bni_ocr_text(sample, drive_url="https://drive.google.com/bni")
    assert len(txs) == 1
    assert txs[0].bank == "BNI"
    assert txs[0].tanggal == "2026-11-16"
    assert txs[0].tipe == "MASUK"
    assert txs[0].nominal == 500000
    assert txs[0].saldo == 3350000


def test_receipt_classification_valid_and_anomaly():
    valid_ocr = """
    BRImo
    Transfer Berhasil
    17 Nov 2026
    Nominal Rp 150.000
    Rekening Tujuan 12345678
    """
    tx, reason = classify_and_parse_receipt(valid_ocr, drive_url="https://drive.google.com/img1")
    assert reason is None
    assert tx is not None
    assert tx.bank == "BRI"
    assert tx.tipe == "KELUAR"
    assert tx.nominal == 150000
    assert tx.tanggal == "2026-11-17"

    non_tx_ocr = "Selamat pagi, ini foto pemandangan gunung bromo"
    tx2, reason2 = classify_and_parse_receipt(non_tx_ocr, drive_url="https://drive.google.com/img2")
    assert tx2 is None
    assert reason2 is not None


def test_matcher_finds_matching_mutasi_row():
    rows = [
        (
            2,
            {
                "Tanggal": "2026-11-17",
                "Tipe (MASUK/KELUAR)": "KELUAR",
                "Nominal": 150000,
                "Sumber": "MUTASI",
                "Status Match": "UNMATCHED",
            },
        ),
        (
            3,
            {
                "Tanggal": "2026-11-17",
                "Tipe (MASUK/KELUAR)": "MASUK",
                "Nominal": 500000,
                "Sumber": "MUTASI",
                "Status Match": "MATCHED",
            },
        ),
    ]
    receipt = Transaction(
        bank="BRI",
        tanggal="2026-11-18",  # +1 day tolerance
        tipe="KELUAR",
        nominal=150000,
        keterangan="Bukti BRImo",
        sumber="TRANSAKSI",
        link_bukti="https://drive.google.com/img1",
    )
    match = find_matching_row(rows, receipt, target_source="MUTASI")
    assert match is not None
    assert match[0] == 2
