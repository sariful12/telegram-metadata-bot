"""Telegram bot version of the Image Metadata Remover.

Send an image (photo or file) and the bot strips its metadata — EXIF,
GPS, camera data and AI / C2PA / XMP labels — then sends the clean
image back as a file you can download.

Setup (see README.md): create a bot with @BotFather, set BOT_TOKEN,
and either set WEBHOOK_URL or deploy on Render (RENDER_EXTERNAL_URL
is picked up automatically). The token is read from the environment
only — it is never hardcoded and never logged.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from clean import SUPPORTED_EXTENSIONS, clean_image

MAX_FILE_SIZE = 20 * 1024 * 1024  # Telegram Bot API limit for downloads

START_TEXT = (
    "👋 Hi! I'm the Image Metadata Remover bot.\n\n"
    "Send me an image and I'll strip its hidden metadata — EXIF, GPS "
    "location, camera data and AI / C2PA labels — then send you back a "
    "clean copy to download.\n\n"
    "✅ JPG, PNG and WebP\n"
    "📎 Tip: send the image as a *file* (paperclip, not the gallery) "
    "to keep the original quality — photos sent as photos are "
    "re-compressed by Telegram first.\n\n"
    "🔒 Your images are only used to clean them and are deleted right "
    "after. One honest note: invisible watermarks hidden *inside* the "
    "pixels (like Google's SynthID) can't be removed — this only "
    "strips metadata stored in the file."
)

UNSUPPORTED_TEXT = (
    "I only clean images — please send a JPG, PNG or WebP file. "
    "Photos work too, but sending as a file keeps the original quality."
)

log = logging.getLogger(__name__)


def _clean_filename(name: str) -> str:
    stem = Path(name).stem or "image"
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        ext = ".jpg"
    return f"{stem}-clean{ext}"


def _report_text(report: dict, is_photo: bool) -> str:
    lines = []
    if report["ai_label"]:
        lines.append("⚠️ *AI label found — removed.*")
    if report["already_clean"]:
        lines.append("✅ Already clean — no metadata found. "
                     "Here's a fresh copy anyway.")
    else:
        removed = ", ".join(report["removed"])
        lines.append(f"✅ Cleaned — removed: {removed}.")
    if report["ai_label"]:
        lines.append(
            "Note: invisible watermarks inside the pixels (like SynthID) "
            "can't be removed — only the file's AI label was stripped.")
    if is_photo:
        lines.append(
            "Tip: send as a file (📎) next time to keep the original quality.")
    return "\n".join(lines)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(START_TEXT, parse_mode="Markdown")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Send me an image and I'll clean its metadata for you. "
        "JPG, PNG or WebP — as a photo or as a file.")


async def _process_file(update: Update, tg_file, original_name: str,
                        is_photo: bool) -> None:
    message = update.message
    if tg_file.file_size and tg_file.file_size > MAX_FILE_SIZE:
        await message.reply_text(
            "That file is over Telegram's 20 MB bot limit, so I can't "
            "download it. Try a smaller copy.")
        return

    await message.reply_text("Cleaning… 🧹")
    with tempfile.TemporaryDirectory(prefix="meta-bot-") as tmp:
        in_path = Path(tmp) / ("input" + Path(original_name).suffix.lower())
        out_path = Path(tmp) / _clean_filename(original_name)
        try:
            await tg_file.download_to_drive(in_path)
            report = await asyncio.to_thread(clean_image, in_path, out_path)
        except ValueError:
            await message.reply_text(
                "Sorry, I couldn't read that file — it may be corrupt or "
                "an unsupported format. Try a JPG, PNG or WebP image.")
            return
        except Exception:
            log.exception("failed to process %s", original_name)
            await message.reply_text(
                "Sorry, something went wrong while cleaning that image. "
                "Please try again.")
            return

        caption = _report_text(report, is_photo)
        with open(out_path, "rb") as fh:
            await message.reply_document(
                document=fh,
                filename=out_path.name,
                caption=caption,
                parse_mode="Markdown",
            )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Telegram photos arrive re-encoded as JPEG; take the largest size.
    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    await _process_file(update, tg_file, "photo.jpg", is_photo=True)


async def handle_document(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    doc = update.message.document
    name = doc.file_name or "image"
    mime = (doc.mime_type or "").lower()
    ext = Path(name).suffix.lower()
    if mime not in ("image/jpeg", "image/png", "image/webp") \
            and ext not in SUPPORTED_EXTENSIONS:
        await update.message.reply_text(UNSUPPORTED_TEXT)
        return
    tg_file = await doc.get_file()
    await _process_file(update, tg_file, name, is_photo=False)


def build_app(token: str):
    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,
                                   handle_text))
    return app


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # Never log the bot token: keep the telegram/httpx loggers quiet.
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    token = os.environ.get("BOT_TOKEN")
    if not token:
        print("BOT_TOKEN is not set. Create a bot with @BotFather and set "
              "BOT_TOKEN in the environment (on Render: an env var).",
              file=sys.stderr)
        sys.exit(2)

    base = os.environ.get("WEBHOOK_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if not base:
        print("Set WEBHOOK_URL to your public URL, or deploy on Render — "
              "Render sets RENDER_EXTERNAL_URL automatically.",
              file=sys.stderr)
        sys.exit(2)

    webhook_url = base.rstrip("/") + "/" + token
    port = int(os.environ.get("PORT", "8443"))

    app = build_app(token)

    # Python 3.12+ no longer creates an event loop implicitly, and
    # python-telegram-bot's run_webhook() still calls get_event_loop().
    # Create one explicitly so the webhook starts on every Python
    # (Render runs Python 3.14, where the implicit loop is gone).
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    log.info("Starting webhook on port %d", port)
    app.run_webhook(listen="0.0.0.0", port=port, url_path=token,
                    webhook_url=webhook_url)


if __name__ == "__main__":
    main()
