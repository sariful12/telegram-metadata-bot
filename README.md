# Telegram Metadata Remover Bot

Telegram bot version of the [Image Metadata Remover](https://sariful12.github.io/image-metadata-remover)
(`github.com/sariful12/image-metadata-remover`).

Send the bot an image and it strips the hidden metadata — EXIF, GPS
location, camera data and AI / C2PA / XMP labels — then sends back a
clean copy you can download. Same rules as the web tool: the image is
rebuilt from pixels only, same size, JPG quality 95, PNG lossless,
WebP quality 95.

## What it does

- `/start` — explains how to use the bot.
- Send a **photo** — cleaned and sent back as a file. (Telegram
  re-compresses photos, so for the original quality send it as a file.)
- Send an **image file** (JPG, PNG, WebP) — cleaned and sent back as
  `<name>-clean.<ext>`, with a short note listing what was removed
  (EXIF, GPS, AI label) or "already clean" when nothing was found.
- Anything else is politely declined.

## Honest limit

This removes metadata stored *in the file*. Some AI services also hide
an invisible watermark *inside the pixels* (for example Google's
SynthID). That is part of the picture, not metadata, so no metadata
remover can take it out — the bot says so in its reply when an AI
label is found, and never claims otherwise.

## Deploy (free, on Render)

1. **Create the bot** — in Telegram, open [@BotFather](https://t.me/BotFather),
   send `/newbot`, pick a name and a username. Copy the token it gives
   you. Never share the token in chat or commit it to a repo.
2. **Push this folder to GitHub** as a repo (e.g.
   `telegram-metadata-bot`).
3. **Render** — [dashboard.render.com](https://dashboard.render.com) →
   New → Web Service → connect the repo. Render detects `render.yaml`
   (free plan, Python). Add one environment variable:
   - `BOT_TOKEN` — the token from @BotFather.
   - `WEBHOOK_URL` — leave unset; Render sets `RENDER_EXTERNAL_URL`
     automatically and the bot uses it for the webhook.
4. Deploy. On first start the bot registers its webhook with Telegram.
5. **Test** — open your bot in Telegram, send `/start`, then send an
   image. You should get the clean copy back within seconds.

Notes:

- Render's free tier spins the service down after ~15 minutes idle.
  The first message after that takes a few seconds while it wakes up;
  Telegram retries, so nothing is lost.
- Telegram's Bot API limit is 20 MB per file — bigger files are
  declined with a friendly message.
- Images are downloaded only to clean them and are deleted right after.

## Run locally (test)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python tests/test_clean.py   # cleaner tests, no token needed
```

To run the bot itself locally you need a public URL for the webhook
(e.g. `ngrok http 8443`), then:

```bash
BOT_TOKEN=... WEBHOOK_URL=https://<your-public-url> python bot.py
```

## Files

- `bot.py` — Telegram bot (python-telegram-bot v21, webhook mode).
- `clean.py` — metadata scanner + pixel-only cleaner (Pillow).
  Detection rules mirror the web tool's `index.html`.
- `requirements.txt`, `render.yaml` — dependencies and Render config.
- `tests/test_clean.py` — builds test images with EXIF/GPS, XMP AI
  labels, C2PA JUMBF and PNG text chunks, and verifies the cleaner.
