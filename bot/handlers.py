import asyncio
import html
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
                reply = f"❌ Gagal memproses PDF: {html.escape(str(exc))}"

        await status_msg.edit_text(
            reply, parse_mode="HTML", disable_web_page_preview=True
        )

    async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg:
            return

        caption = msg.caption or ""
        sender = msg.from_user.full_name if msg.from_user else "Unknown"

        if msg.photo:
            file_obj = msg.photo[-1]
            filename = f"{file_obj.file_unique_id}.jpg"
        elif msg.document:
            file_obj = msg.document
            filename = msg.document.file_name or f"{file_obj.file_unique_id}.jpg"
        else:
            return

        status_msg = await msg.reply_text("⏳ Memproses foto...")

        with tempfile.TemporaryDirectory() as tmpdir:
            local_path = os.path.join(tmpdir, filename)
            try:
                tg_file = await file_obj.get_file(read_timeout=30.0)
                await tg_file.download_to_drive(local_path, read_timeout=60.0)
                reply = await asyncio.to_thread(
                    pipeline.process_photo, local_path, filename, caption, sender
                )
            except Exception as exc:
                reply = f"❌ Gagal memproses foto: {html.escape(str(exc))}"

        await status_msg.edit_text(
            reply, parse_mode="HTML", disable_web_page_preview=True
        )

    async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.message
        if not msg or not msg.document:
            return

        doc = msg.document
        filename = (doc.file_name or "").lower()
        mime = (doc.mime_type or "").lower()

        if filename.endswith(".pdf") or mime == "application/pdf":
            await handle_pdf(update, context)
        elif mime.startswith("image/") or filename.endswith(
            (".jpg", ".jpeg", ".png", ".webp", ".bmp")
        ):
            await handle_photo(update, context)
        else:
            await msg.reply_text(
                "⚠️ Format file tidak didukung. Kirim PDF mutasi atau foto/gambar (.jpg/.png/.webp)."
            )

    app.add_handler(CommandHandler(["start", "help"], start_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    return app
