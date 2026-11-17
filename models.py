from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

BankType = Literal["BNI", "BRI", "ANOMALI"]
DirectionType = Literal["MASUK", "KELUAR", "UNKNOWN"]
SourceType = Literal["MUTASI", "TRANSAKSI"]


@dataclass
class Transaction:
    bank: BankType
    tanggal: str  # Normalized YYYY-MM-DD (or raw string if unparsed)
    tipe: DirectionType
    nominal: int  # Amount in IDR (integer)
    keterangan: str
    saldo: Optional[int] = None
    sumber: SourceType = "MUTASI"
    status_match: str = "UNMATCHED"
    link_mutasi: str = ""
    link_bukti: str = ""

    def to_sheet_row(self) -> list:
        return [
            self.tanggal,
            self.tipe,
            self.nominal,
            self.keterangan,
            self.saldo if self.saldo is not None else "",
            self.sumber,
            self.status_match,
            self.link_mutasi,
            self.link_bukti,
        ]


@dataclass
class AnomalyRecord:
    sender: str
    alasan: str
    raw_ocr_text: str
    link_file: str
    waktu_upload: str = field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    def to_sheet_row(self) -> list:
        return [
            self.waktu_upload,
            self.sender,
            self.alasan,
            self.raw_ocr_text[:1000],  # Keep cell size safe
            self.link_file,
        ]
