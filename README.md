# Mutasi & Bukti Transfer Bot → Google Sheets

Telegram bot that collects bank statements (PDF) and transfer receipts (images), stores raw files in Google Drive, extracts transactions via `pdfplumber` / Tesseract OCR, reconciles them, and outputs 3 Google Sheets: **BNI**, **BRI**, and **ANOMALI**.

## Module Ownership
- `bot/handlers.py` & `main.py` — Telegram Bot & Main Orchestrator
- `services/drive_service.py` — Google Drive upload + shareable link
- `services/sheets_service.py` — Google Sheets writer (`BNI`, `BRI`, `ANOMALI`)
- `services/matcher.py` — Receipt-to-mutasi reconciliation
- `extractors/bri_pdf.py` — BRI PDF extractor (`pdfplumber`)
- `extractors/bni_ocr.py` — BNI PDF OCR extractor (`pdf2image` + `pytesseract`)
- `extractors/image_ocr.py` — Receipt image OCR & anomaly classifier (`pytesseract` + OpenCV)

## Setup
1. Install system dependencies:
   - Ubuntu/Debian: `sudo apt-get install tesseract-ocr tesseract-ocr-ind poppler-utils`
   - macOS: `brew install tesseract tesseract-lang poppler`
2. Install Python packages:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. Configure Google Cloud:
   - Enable **Google Drive API** and **Google Sheets API**.
   - Create a **Service Account**, download `credentials.json` to the project root.
   - Share your Drive folder and 3 Google Sheets with the Service Account `client_email` as **Editor**.
4. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`, `GOOGLE_DRIVE_FOLDER_ID`, and the 3 Spreadsheet IDs.
5. Run the bot:
   ```bash
   python main.py
   ```
6. Run unit tests:
   ```bash
   pytest tests/
   ```

## Deploy to VPS with Docker
```bash
git clone https://github.com/VUXXE/mutasi-gsheets-bot.git
cd mutasi-gsheets-bot
cp .env.example .env
# Edit .env and place credentials.json in this directory
docker compose up -d --build
```
Check logs:
```bash
docker compose logs -f
```

