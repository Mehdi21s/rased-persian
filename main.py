import asyncio
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl import functions

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("arabic-to-persian")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID = int(os.environ["ADMIN_ID"])
# Configure one or more sources. Preferred: SOURCE_CHANNELS="@source1,@source2".
# Backward compatible: SOURCE_CHANNEL plus optional SOURCE_CHANNEL_2.
def _read_source_channels():
    combined = os.getenv("SOURCE_CHANNELS", "").strip()
    if combined:
        values = [item.strip() for item in combined.split(",") if item.strip()]
    else:
        values = [
            os.getenv("SOURCE_CHANNEL", "@rasedal3ado138e").strip(),
            os.getenv("SOURCE_CHANNEL_2", "@SolIalIe").strip(),
        ]
        values = [item for item in values if item]
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(values))

SOURCE_CHANNELS = _read_source_channels()
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "@rasedpersian")
SETTINGS_FILE = Path(os.getenv("SETTINGS_FILE", "settings.json"))


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"tag": str(data.get("tag", "@rasedpersian"))}
    except (OSError, json.JSONDecodeError):
        pass
    return {"tag": os.getenv("POST_TAG", "@rasedpersian")}


settings = load_settings()
settings_lock = threading.Lock()


def save_settings():
    with settings_lock:
        SETTINGS_FILE.write_text(
            json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get_tag():
    with settings_lock:
        return settings.get("tag", "").strip()


def is_admin(event):
    return bool(event.sender_id == ADMIN_ID)


user_client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
panel_client = TelegramClient("panel_bot_session", API_ID, API_HASH)


async def translate_message(message, peer):
    """Use Telegram's own MTProto translation method, not an external translator."""
    source_text = message.message or ""
    if not source_text.strip():
        return ""
    result = await user_client(
        functions.messages.TranslateTextRequest(
            peer=peer,
            id=[message.id],
            to_lang="fa",
        )
    )
    items = getattr(result, "result", None) or []
    if not items:
        raise RuntimeError("Telegram returned no translated text")
    return (items[0].text or "").strip()


def with_tag(text, tag):
    text = (text or "").strip()
    tag = (tag or "").strip()
    if not tag:
        return text
    return f"{text}\n\n{tag}" if text else tag


async def translate_and_publish(messages, source_peer, target_peer):
    # Prevent double publishing: ordinary NewMessage handler ignores grouped media;
    # albums are handled here as a single unit.
    messages = sorted(messages, key=lambda m: m.id)
    media_messages = [m for m in messages if m.media]
    if not media_messages:
        for message in messages:
            if not (message.message or "").strip():
                continue
            translated = await translate_message(message, source_peer)
            if not translated:
                log.warning("Empty translation for source message %s; skipped", message.id)
                continue
            await user_client.send_message(target_peer, with_tag(translated, get_tag()), link_preview=False)
            log.info("Published text message %s", message.id)
        return

    # Usually only the first item of a Telegram album carries a caption.
    captions = []
    for message in messages:
        text = (message.message or "").strip()
        if text:
            captions.append((message, await translate_message(message, source_peer)))
    translated_caption = captions[0][1] if captions else ""
    tag = get_tag()

    # Telegram media captions are limited; keep media safe by moving long translated
    # captions to a separate text post instead of failing the entire album send.
    if translated_caption and len(with_tag(translated_caption, tag)) <= 900:
        caption = with_tag(translated_caption, tag)
        await user_client.send_file(
            target_peer,
            [m for m in media_messages],
            caption=caption,
        )
    else:
        await user_client.send_file(target_peer, [m for m in media_messages])
        if translated_caption:
            await user_client.send_message(
                target_peer, with_tag(translated_caption, tag), link_preview=False
            )
        elif tag:
            await user_client.send_message(target_peer, tag, link_preview=False)
    log.info("Published media group/message %s", ",".join(str(m.id) for m in messages))


async def on_new_message(event):
    if getattr(event.message, "grouped_id", None):
        return
    try:
        source_peer = await user_client.get_input_entity(event.chat_id)
        target_peer = await user_client.get_input_entity(TARGET_CHANNEL)
        log.info("Received source message: channel=%s message_id=%s", event.chat_id, event.message.id)
        await translate_and_publish([event.message], source_peer, target_peer)
    except Exception:
        log.exception(
            "Failed processing source message: channel=%s message_id=%s",
            getattr(event, "chat_id", "unknown"), event.message.id
        )


async def on_album(event):
    try:
        source_peer = await user_client.get_input_entity(event.chat_id)
        target_peer = await user_client.get_input_entity(TARGET_CHANNEL)
        message_ids = ",".join(str(m.id) for m in event.messages)
        log.info("Received source album: channel=%s message_ids=%s", event.chat_id, message_ids)
        await translate_and_publish(list(event.messages), source_peer, target_peer)
    except Exception:
        log.exception("Failed processing album: channel=%s", getattr(event, "chat_id", "unknown"))


PANEL_TEXT = (
    "پنل مدیریت ربات ترجمه عربی به فارسی\n\n"
    "از دکمه‌ها یا دستورها استفاده کن.\n"
    "/tag — نمایش تگ فعلی\n"
    "/settag متن_تگ — تغییر تگ\n"
    "/status — وضعیت کانال‌ها"
)


@panel_client.on(events.NewMessage(pattern=r"^/start(?:@\w+)?$"))
async def panel_start(event):
    if not is_admin(event):
        await event.reply("این پنل فقط برای مدیر ربات فعال است.")
        return
    await event.reply(
        PANEL_TEXT,
        buttons=[
            [Button.inline("🏷 تنظیم تگ", b"settag"), Button.inline("📌 تگ فعلی", b"showtag")],
            [Button.inline("📡 وضعیت", b"status")],
        ],
    )


@panel_client.on(events.CallbackQuery)
async def panel_callbacks(event):
    if event.sender_id != ADMIN_ID:
        await event.answer("دسترسی ندارید", alert=True)
        return
    data = event.data or b""
    if data == b"settag":
        await event.answer()
        await event.respond("برای تنظیم تگ این دستور را بفرست:\n/settag @YourTag")
    elif data == b"showtag":
        await event.answer()
        await event.respond("تگ فعلی:\n" + (get_tag() or "(خالی)"))
    elif data == b"status":
        await event.answer()
        await event.respond(
            f"منابع: {', '.join(SOURCE_CHANNELS)}\nمقصد: {TARGET_CHANNEL}\nتگ: {get_tag() or '(خالی)'}"
        )


@panel_client.on(events.NewMessage(pattern=r"^/tag(?:@\w+)?$"))
async def panel_tag(event):
    if not is_admin(event):
        return
    await event.reply("تگ فعلی:\n" + (get_tag() or "(خالی)"))


@panel_client.on(events.NewMessage(pattern=r"^/settag(?:@\w+)?(?:\s+([\s\S]+))?$"))
async def panel_settag(event):
    if not is_admin(event):
        await event.reply("دسترسی ندارید.")
        return
    value = (event.pattern_match.group(1) or "").strip()
    if not value:
        await event.reply("تگ را بعد از دستور بنویس؛ نمونه:\n/settag @rasedpersian")
        return
    if len(value) > 100:
        await event.reply("تگ خیلی طولانی است؛ حداکثر ۱۰۰ نویسه.")
        return
    with settings_lock:
        settings["tag"] = value
    try:
        save_settings()
    except OSError:
        log.exception("Could not save settings file")
        await event.reply("تگ برای این اجرا تغییر کرد، اما ذخیره‌سازی فایل ناموفق بود.")
        return
    await event.reply("تگ ذخیره شد و از پست بعدی استفاده می‌شود:\n" + value)


@panel_client.on(events.NewMessage(pattern=r"^/status(?:@\w+)?$"))
async def panel_status(event):
    if not is_admin(event):
        return
    await event.reply(
        f"وضعیت: فعال\nمنابع: {', '.join(SOURCE_CHANNELS)}\nمقصد: {TARGET_CHANNEL}\nتگ: {get_tag() or '(خالی)'}\nترجمه: API ترجمه تلگرام به فارسی"
    )


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"Arabic-to-Persian Telegram repost bot is running.\n"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Health page listening on port %s", port)


async def main():
    start_health_server()
    await user_client.start()
    log.info("User account connected; sources=%s target=%s", ",".join(SOURCE_CHANNELS), TARGET_CHANNEL)
    await panel_client.start(bot_token=BOT_TOKEN)
    log.info("Admin panel bot connected")

    # Resolve all source channels early so configuration/access problems are visible.
    if not SOURCE_CHANNELS:
        raise RuntimeError("No source channels configured. Set SOURCE_CHANNELS or SOURCE_CHANNEL.")
    for source in SOURCE_CHANNELS:
        await user_client.get_entity(source)
        log.info("Source channel ready: %s", source)
    await user_client.get_entity(TARGET_CHANNEL)
    user_client.add_event_handler(on_new_message, events.NewMessage(chats=SOURCE_CHANNELS))
    user_client.add_event_handler(on_album, events.Album(chats=SOURCE_CHANNELS))
    log.info("STARTUP_MARKER=ARABIC_TO_PERSIAN_TELEGRAM_TRANSLATOR_V2_TWO_SOURCES")
    await asyncio.gather(user_client.run_until_disconnected(), panel_client.run_until_disconnected())


if __name__ == "__main__":
    asyncio.run(main())
