import json
import re
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
    "Tipe",
    "Nominal",
    "Keterangan",
    "Saldo",
    "Sumber",
    "Status Match",
    "File Mutasi",
    "Bukti Transfer",
]

ANOMALI_HEADERS = [
    "Waktu Upload",
    "Pengirim",
    "Alasan Anomali",
    "Cuplikan OCR",
    "File",
]


def _to_hyperlink(url: str, label: str) -> str:
    if not url:
        return ""
    if url.startswith("=HYPERLINK("):
        return url
    safe_url = url.replace('"', "")
    return f'=HYPERLINK("{safe_url}", "{label}")'


def _extract_url(cell_val: str) -> str:
    val = str(cell_val or "").strip()
    m = re.match(r'^=HYPERLINK\("([^"]+)"', val, re.IGNORECASE)
    return m.group(1) if m else val


class SheetsService:
    def __init__(self, config: Config) -> None:
        self.config = config
        if config.google_credentials_json:
            info = json.loads(config.google_credentials_json)
            creds = Credentials.from_service_account_info(info, scopes=SHEETS_SCOPES)
        else:
            creds = Credentials.from_service_account_file(
                config.google_credentials_path, scopes=SHEETS_SCOPES
            )
        self.client = gspread.authorize(creds)
        self._formatted_tabs: set[str] = set()

    def _apply_sheet_formatting(
        self, spreadsheet: gspread.Spreadsheet, ws: gspread.Worksheet, is_anomali: bool
    ) -> None:
        key = f"{spreadsheet.id}:{ws.id}"
        if key in self._formatted_tabs:
            return

        last_col = "E" if is_anomali else "I"
        ws.freeze(rows=1)
        ws.format(
            f"A1:{last_col}1",
            {
                "backgroundColor": {"red": 0.12, "green": 0.16, "blue": 0.23},
                "textFormat": {
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "bold": True,
                    "fontSize": 10,
                },
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
            },
        )

        if not is_anomali:
            ws.format(
                "C2:C1000",
                {
                    "numberFormat": {"type": "CURRENCY", "pattern": '"Rp"#,##0'},
                    "horizontalAlignment": "RIGHT",
                },
            )
            ws.format(
                "E2:E1000",
                {
                    "numberFormat": {"type": "CURRENCY", "pattern": '"Rp"#,##0'},
                    "horizontalAlignment": "RIGHT",
                },
            )
            ws.format("A2:B1000", {"horizontalAlignment": "CENTER"})
            ws.format("F2:I1000", {"horizontalAlignment": "CENTER"})
            ws.format("D2:D1000", {"wrapStrategy": "WRAP"})
            col_widths = [110, 90, 130, 320, 130, 100, 115, 115, 120]
        else:
            ws.format("D2:D1000", {"wrapStrategy": "WRAP"})
            col_widths = [150, 140, 240, 340, 110]

        requests = [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": ws.id,
                        "dimension": "COLUMNS",
                        "startIndex": idx,
                        "endIndex": idx + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
            for idx, width in enumerate(col_widths)
        ]
        spreadsheet.batch_update({"requests": requests})
        self._formatted_tabs.add(key)

    def _get_worksheet(self, bank: BankType) -> gspread.Worksheet:
        if bank == "BNI":
            ss_id = self.config.bni_spreadsheet_id
            ws_name = self.config.bni_worksheet_name
            headers = TRANSACTION_HEADERS
            is_anomali = False
        elif bank == "BRI":
            ss_id = self.config.bri_spreadsheet_id
            ws_name = self.config.bri_worksheet_name
            headers = TRANSACTION_HEADERS
            is_anomali = False
        else:
            ss_id = self.config.anomali_spreadsheet_id
            ws_name = self.config.anomali_worksheet_name
            headers = ANOMALI_HEADERS
            is_anomali = True

        spreadsheet = self.client.open_by_key(ss_id)
        try:
            ws = spreadsheet.worksheet(ws_name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=ws_name, rows=1000, cols=len(headers))

        if not ws.row_values(1):
            ws.append_row(headers, value_input_option="USER_ENTERED")
        else:
            # Update row 1 to clean headers if column count matches
            existing = ws.row_values(1)
            if len(existing) == len(headers) and existing != headers:
                last_col = "E" if is_anomali else "I"
                ws.update(f"A1:{last_col}1", [headers])

        self._apply_sheet_formatting(spreadsheet, ws, is_anomali=is_anomali)
        return ws

    def append_transactions(self, bank: BankType, txs: List[Transaction]) -> int:
        if not txs:
            return 0
        ws = self._get_worksheet(bank)
        rows = []
        for tx in txs:
            row = tx.to_sheet_row()
            row[7] = _to_hyperlink(tx.link_mutasi, "Lihat PDF")
            row[8] = _to_hyperlink(tx.link_bukti, "Lihat Bukti")
            rows.append(row)
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)

    def append_anomaly(self, record: AnomalyRecord) -> None:
        ws = self._get_worksheet("ANOMALI")
        row = record.to_sheet_row()
        row[4] = _to_hyperlink(record.link_file, "Lihat File")
        ws.append_row(row, value_input_option="USER_ENTERED")

    def get_all_rows_with_index(self, bank: BankType) -> list[tuple[int, dict]]:
        """Return (1-based sheet row_number, row_dict) for matching."""
        ws = self._get_worksheet(bank)
        all_values = ws.get_all_values(value_render_option="FORMULA")
        if len(all_values) <= 1:
            return []

        headers = all_values[0]
        rows: list[tuple[int, dict]] = []
        for idx, row in enumerate(all_values[1:], start=2):
            rec: dict = {}
            for col_i, h in enumerate(headers):
                if h and h not in rec:
                    val = row[col_i] if col_i < len(row) else ""
                    rec[h] = _extract_url(val) if isinstance(val, str) and val.startswith("=HYPERLINK(") else val
            rows.append((idx, rec))
        return rows

    def mark_row_matched(
        self,
        bank: BankType,
        row_number: int,
        link_bukti: str = "",
        link_mutasi: str = "",
    ) -> None:
        ws = self._get_worksheet(bank)
        ws.update_cell(row_number, 7, "MATCHED")
        if link_mutasi:
            ws.update_cell(row_number, 8, _to_hyperlink(link_mutasi, "Lihat PDF"))
        if link_bukti:
            ws.update_cell(row_number, 9, _to_hyperlink(link_bukti, "Lihat Bukti"))
