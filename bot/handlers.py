import asyncio
import os
import tempfile
from typing import Protocol
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


class PipelineProtocol(Protocol):
    def process_pdf(self, local_path: str, filename: str, caption: str, sender: str) -> str: ...
    def process_photo(self, local_path: str, filename: str, caption: str, sender: str) -> str: ...


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    await update.message.reply_text(
        "Halo! Kirim file ke bot ini untuk diproses ke Google Sheets:\n"
        "1. PDF Mutasi (sertakan caption 'BNI' atau 'BRI')\n"
        "2. Foto Bukti Transfer (otomatis masuk BNI / BRI / ANOMALI)"
    )


def build_telegram_app(token: str, pipeline: PipelineProtocol) -> Application:
    app = (
        Application.builder()
        .token(token)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .get_updates_read_timeout(30.0)
        .build()
    )

    async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg or not msg.document:
            return

        doc = msg.document
        filename = doc.file_name or "mutasi.pdf"
        caption = msg.caption or ""
        sender = msg.from_user.full_name if msg.from_user else "Unknown"

        status_msg = await msg.reply_text("⏳ Memproses PDF mutasi...")

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, filename)
            try:
                tg_file = await doc.get_file(read_timeout=30.0)
                await tg_file.download_to_drive(local_path, read_timeout=60.0)
                reply = await asyncio.to_thread(
                    pipeline.process_pdf, local_path, filename, caption, sender
                )
            except Exception as exc:
                reply = f"❌ Gagal memproses PDF: {exc}"

        await status_msg.edit_text(reply)

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg or not msg.photo:
            return

        photo = msg.photo[-1]  # Highest resolution
        caption = msg.caption or ""
        sender = msg.from_user.full_name if msg.from_user else "Unknown"

        status_msg = await msg.reply_text("⏳ Memproses foto...")

        with tempfile.TemporaryDirectory() as tmpdir:
            filename = f"{photo.file_unique_id}.jpg"
            local_path = os.path.join(tmpdir, filename)
            try:
                tg_file = await photo.get_file(read_timeout=30.0)
                await tg_file.download_to_drive(local_path, read_timeout=60.0)
                reply = await asyncio.to_thread(
                    pipeline.process_photo, local_path, filename, caption, sender
                )
            except Exception as exc:
                reply = f"❌ Gagal memproses foto: {exc}"

        await status_msg.edit_text(reply)

    app.add_handler(CommandHandler(["start", "help"], start_cmd))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    return app
