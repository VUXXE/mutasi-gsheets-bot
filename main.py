import logging
import os
import time
from datetime import datetime
import pdfplumber

from bot.handlers import build_telegram_app
from config import Config, load_config
from extractors.bni_ocr import extract_bni_mutasi
from extractors.bri_pdf import extract_bri_mutasi
from extractors.common import configure_tesseract
from extractors.image_ocr import extract_receipt_image
from models import AnomalyRecord, BankType
from services.drive_service import DriveService
from services.matcher import match_receipt_against_sheet, reconcile_mutasi_batch
from services.sheets_service import SheetsService

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("mutasi-bot")


HARI_ID = [
    "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"
]
BULAN_ID = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni",
    "Juli", "Agustus", "September", "Oktober", "November", "Desember"
]


def format_tanggal_id(iso_date: str) -> str:
    try:
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return f"{HARI_ID[dt.weekday()]}, {dt.day:02d} {BULAN_ID[dt.month]} {dt.year}"
    except ValueError:
        return iso_date


def detect_pdf_bank(local_path: str, filename: str, caption: str) -> BankType | None:
    hint = f"{filename} {caption}".lower()
    if "bri" in hint:
        return "BRI"
    if "bni" in hint:
        return "BNI"

    # Fallback: peek first page text via pdfplumber
    try:
        with pdfplumber.open(local_path) as pdf:
            if pdf.pages:
                text = (pdf.pages[0].extract_text() or "").lower()
                if "bri" in text or "bank rakyat indonesia" in text:
                    return "BRI"
                if "bni" in text or "bank negara indonesia" in text:
                    return "BNI"
    except Exception:
        pass
    return None


class AppPipeline:
    def __init__(self, config: Config) -> None:
        self.config = config
        configure_tesseract(config.tesseract_cmd)
        self._drive: DriveService | None = None
        self._sheets: SheetsService | None = None

    def _ensure_google_services(self) -> tuple[DriveService, SheetsService]:
        if not self.config.google_credentials_json and not os.path.exists(
            self.config.google_credentials_path
        ):
            raise RuntimeError(
                "Google credentials belum dikonfigurasi (set GOOGLE_CREDENTIALS_JSON di InstaCloud)."
            )
        if self._drive is None:
            self._drive = DriveService(
                self.config.google_credentials_path,
                self.config.drive_folder_id,
                credentials_json=self.config.google_credentials_json,
            )
        if self._sheets is None:
            self._sheets = SheetsService(self.config)
        return self._drive, self._sheets

    def process_pdf(self, local_path: str, filename: str, caption: str, sender: str) -> str:
        drive, sheets = self._ensure_google_services()
        bank = detect_pdf_bank(local_path, filename, caption)
        if bank not in ("BRI", "BNI"):
            return (
                "⚠️ Bank tidak terdeteksi (BNI/BRI). "
                "Kirim ulang PDF dengan caption 'BNI' atau 'BRI'."
            )

        drive_url = drive.upload_file(local_path, filename=filename)

        if bank == "BRI":
            mutasi_list = extract_bri_mutasi(local_path, drive_url=drive_url)
        else:
            mutasi_list = extract_bni_mutasi(local_path, drive_url=drive_url)

        if not mutasi_list:
            return (
                f"⚠️ Tidak ada baris mutasi {bank} yang berhasil diekstrak.\n"
                f"File tersimpan di Drive: {drive_url}"
            )

        inserted, matched = reconcile_mutasi_batch(sheets, bank, mutasi_list)
        return (
            f"✅ Mutasi {bank} selesai diproses!\n"
            f"• Total transaksi masuk sheet {bank}: {inserted}\n"
            f"• Bukti transfer yang MATCHED: {matched}\n"
            f"• File: {drive_url}"
        )

    def process_photo(self, local_path: str, filename: str, caption: str, sender: str) -> str:
        drive, sheets = self._ensure_google_services()
        drive_url = drive.upload_file(local_path, filename=filename)
        tx, anomaly_reason, raw_text = extract_receipt_image(
            local_path,
            drive_url=drive_url,
            hint_text=caption,
        )

        if tx is None:
            record = AnomalyRecord(
                sender=sender,
                alasan=anomaly_reason or "Foto bukan transaksi",
                raw_ocr_text=raw_text,
                link_file=drive_url,
            )
            sheets.append_anomaly(record)
            return (
                f"⚠️ Foto masuk ke sheet ANOMALI.\n"
                f"• Alasan: {record.alasan}\n"
                f"• Drive: {drive_url}"
            )

        # Allow caption override for MASUK / KELUAR if OCR returned UNKNOWN
        cap_lower = caption.lower()
        if tx.tipe == "UNKNOWN":
            if "masuk" in cap_lower:
                tx.tipe = "MASUK"
            elif "keluar" in cap_lower:
                tx.tipe = "KELUAR"

        matched_row = match_receipt_against_sheet(sheets, tx)
        if matched_row is not None:
            status_line = f"🟢 MATCHED (Baris {matched_row} di tab {tx.bank})"
        else:
            status_line = "🟡 UNMATCHED (Belum ada mutasi yang cocok, dicatat sebagai TRANSAKSI)"
        return (
            f"✅ Bukti transaksi {tx.bank} diproses!\n"
            f"• Status: {status_line}\n"
            f"• Tanggal: {format_tanggal_id(tx.tanggal)}\n"
            f"• Tipe: {tx.tipe}\n"
            f"• Nominal: Rp{tx.nominal:,}\n"
            f"• File: {drive_url}"
        )


def main() -> None:
    config = load_config()
    if not config.telegram_token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN is not set. Waiting for secrets to be configured..."
        )
        while True:
            time.sleep(60)

    pipeline = AppPipeline(config)
    app = build_telegram_app(config.telegram_token, pipeline)
    logger.info("Bot started. Listening for PDFs and photos...")
    app.run_polling()


if __name__ == "__main__":
    main()
