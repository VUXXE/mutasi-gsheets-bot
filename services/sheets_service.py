from typing import List
import gspread
from google.oauth2.service_account import Credentials

from config import Config
from models import AnomalyRecord, BankType, Transaction

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

TRANSACTION_HEADERS = [
    "Tanggal",
    "Tipe (MASUK/KELUAR)",
    "Nominal",
    "Keterangan",
    "Saldo",
    "Sumber",
    "Status Match",
    "Link Mutasi (Drive)",
    "Link Bukti (Drive)",
]

ANOMALI_HEADERS = [
    "Waktu Upload",
    "Pengirim",
    "Alasan Anomali",
    "Raw OCR Text",
    "Link File (Drive)",
]


class SheetsService:
    def __init__(self, config: Config) -> None:
        self.config = config
        creds = Credentials.from_service_account_file(
            config.google_credentials_path, scopes=SHEETS_SCOPES
        )
        self.client = gspread.authorize(creds)

    def _get_worksheet(self, bank: BankType) -> gspread.Worksheet:
        if bank == "BNI":
            ss_id = self.config.bni_spreadsheet_id
            ws_name = self.config.bni_worksheet_name
            headers = TRANSACTION_HEADERS
        elif bank == "BRI":
            ss_id = self.config.bri_spreadsheet_id
            ws_name = self.config.bri_worksheet_name
            headers = TRANSACTION_HEADERS
        else:
            ss_id = self.config.anomali_spreadsheet_id
            ws_name = self.config.anomali_worksheet_name
            headers = ANOMALI_HEADERS

        spreadsheet = self.client.open_by_key(ss_id)
        try:
            ws = spreadsheet.worksheet(ws_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=ws_name, rows=1000, cols=len(headers))

        if not ws.row_values(1):
            ws.append_row(headers, value_input_option="USER_ENTERED")
        return ws

    def append_transactions(self, bank: BankType, txs: List[Transaction]) -> int:
        if not txs:
            return 0
        ws = self._get_worksheet(bank)
        rows = [tx.to_sheet_row() for tx in txs]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)

    def append_anomaly(self, record: AnomalyRecord) -> None:
        ws = self._get_worksheet("ANOMALI")
        ws.append_row(record.to_sheet_row(), value_input_option="USER_ENTERED")

    def get_all_rows_with_index(self, bank: BankType) -> list[tuple[int, dict]]:
        """Return (1-based sheet row_number, row_dict) for matching."""
        ws = self._get_worksheet(bank)
        records = ws.get_all_records()
        # Data starts at row 2 (row 1 is header)
        return [(idx + 2, rec) for idx, rec in enumerate(records)]

    def mark_row_matched(
        self,
        bank: BankType,
        row_number: int,
        link_bukti: str = "",
        link_mutasi: str = "",
    ) -> None:
        ws = self._get_worksheet(bank)
        # Col 7 = Status Match, Col 8 = Link Mutasi, Col 9 = Link Bukti
        ws.update_cell(row_number, 7, "MATCHED")
        if link_mutasi:
            ws.update_cell(row_number, 8, link_mutasi)
        if link_bukti:
            ws.update_cell(row_number, 9, link_bukti)
