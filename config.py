import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_token: str
    google_credentials_path: str
    google_credentials_json: str
    drive_folder_id: str
    bni_spreadsheet_id: str
    bri_spreadsheet_id: str
    anomali_spreadsheet_id: str
    bni_worksheet_name: str
    bri_worksheet_name: str
    anomali_worksheet_name: str
    tesseract_cmd: str


def load_config() -> Config:
    return Config(
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        google_credentials_path=os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"),
        google_credentials_json=os.getenv("GOOGLE_CREDENTIALS_JSON", ""),
        drive_folder_id=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""),
        bni_spreadsheet_id=os.getenv("BNI_SPREADSHEET_ID", ""),
        bri_spreadsheet_id=os.getenv("BRI_SPREADSHEET_ID", ""),
        anomali_spreadsheet_id=os.getenv("ANOMALI_SPREADSHEET_ID", ""),
        bni_worksheet_name=os.getenv("BNI_WORKSHEET_NAME", "BNI"),
        bri_worksheet_name=os.getenv("BRI_WORKSHEET_NAME", "BRI"),
        anomali_worksheet_name=os.getenv("ANOMALI_WORKSHEET_NAME", "ANOMALI"),
        tesseract_cmd=os.getenv("TESSERACT_CMD", ""),
    )
