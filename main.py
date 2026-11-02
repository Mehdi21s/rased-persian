import asyncio, json, logging, os, re, tempfile, urllib.request, urllib.error
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, InputMediaDocument, MessageEntity, ReactionTypeEmoji
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl import types as tl_types

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("news-translator")
log.info("RASED_TRANSLATOR_PREMIUM_EMOJI_V5 starting")

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
SESSION_STRING = os.environ["SESSION_STRING"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
# Accept either SOURCE_CHANNELS (comma-separated) or the older SOURCE_CHANNEL variable.
# SOURCE_CHANNELS takes priority if both are set.
_sources_raw = os.getenv("SOURCE_CHANNELS", "").strip()
if not _sources_raw:
    _sources_raw = os.getenv("SOURCE_CHANNEL", "rasedal3ado138e,kataebAlqasam").strip()
SOURCE_CHANNELS = list(dict.fromkeys(
    x.strip().strip().lstrip("@").strip()
    for x in re.split(r"[,;\n]+", _sources_raw)
    if x.strip().strip().lstrip("@")
))
TARGET_CHANNEL = os.getenv("TARGET_CHANNEL", "@rasedpersian")
TAG_TEXT = os.getenv("TAG_TEXT", "✨ @rasedpersian").strip()
CATCHUP_LIMIT = max(0, int(os.getenv("CATCHUP_LIMIT", "0")))
TRANSLATE_REQUIRED = os.getenv("TRANSLATE_REQUIRED", "true").lower() not in {"0", "false", "no", "off"}
DATA_DIR = Path(os.getenv("DATA_DIR", "/tmp/news-translator"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
SEEN_FILE = DATA_DIR / "seen_posts.json"

proxy = None
if os.getenv("PROXY_HOST") and os.getenv("PROXY_PORT"):
    proxy = ("socks5", os.getenv("PROXY_HOST"), int(os.getenv("PROXY_PORT")))

bot = Bot(token=BOT_TOKEN)
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH, proxy=proxy)
LIBRETRANSLATE_URL = os.getenv("LIBRETRANSLATE_URL", "http://libretranslate.railway.internal:5000/translate")
LIBRETRANSLATE_API_KEY = os.getenv("LIBRETRANSLATE_API_KEY", "")

seen_ids = set()

# Admin panel: set ADMIN_IDS in Railway to comma-separated Telegram numeric user IDs.
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
CONFIG_FILE = DATA_DIR / "bot_config.json"
dp = Dispatcher()
pending_tag_users = set()
TAG_ENTITIES = []

def load_runtime_config():
    global TAG_TEXT, TAG_ENTITIES
    try:
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            TAG_TEXT = str(cfg.get("tag_text", TAG_TEXT))
            TAG_ENTITIES = cfg.get("tag_entities", []) or []
    except Exception:
        log.exception("Could not load bot panel config")

def save_runtime_config():
    CONFIG_FILE.write_text(
        json.dumps({"tag_text": TAG_TEXT, "tag_entities": TAG_ENTITIES},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

def is_admin(user_id):
    return not ADMIN_IDS or user_id in ADMIN_IDS

@dp.message(Command("start", "panel"))
async def panel_command(message):
    if not is_admin(message.from_user.id):
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ تنظیم تگ", callback_data="panel:set_tag")],
        [InlineKeyboardButton(text="📡 وضعیت کانال‌ها", callback_data="panel:status")],
    ])
    await message.answer(
        "پنل مدیریت ربات\n"
        f"کانال‌های مبدأ: {', '.join('@'+x for x in SOURCE_CHANNELS)}\n"
        f"کانال مقصد: {TARGET_CHANNEL}\n"
        f"تگ فعلی: {TAG_TEXT or 'تنظیم نشده'}\n\n"
        "برای تغییر تگ، دکمهٔ «تنظیم تگ» را بزن و پیام تگ را بفرست. "
        "ایموجی سفارشی را مستقیماً در همان پیام قرار بده.",
        reply_markup=keyboard,
    )

@dp.callback_query(F.data == "panel:set_tag")
async def panel_set_tag(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    pending_tag_users.add(callback.from_user.id)
    await callback.message.answer("حالا تگ را در یک پیام بفرست. برای ذخیره ایموجی پریمیوم، آن را مستقیماً داخل همین پیام قرار بده.")
    await callback.answer()

@dp.callback_query(F.data == "panel:status")
async def panel_status(callback):
    if not is_admin(callback.from_user.id):
        await callback.answer("اجازه دسترسی نداری.", show_alert=True)
        return
    await callback.message.answer(
        "وضعیت تنظیمات:\n"
        f"مبدأها ({len(SOURCE_CHANNELS)}): {', '.join('@'+x for x in SOURCE_CHANNELS)}\n"
        f"مقصد: {TARGET_CHANNEL}\n"
        f"تگ: {TAG_TEXT or 'خالی'}\n"
        f"ادمین‌های پنل: {len(ADMIN_IDS) if ADMIN_IDS else 'همه کاربران (ADMIN_IDS تنظیم نشده)'}"
    )
    await callback.answer()

@dp.message(F.text | F.caption)
async def capture_panel_tag(message):
    global TAG_TEXT, TAG_ENTITIES
    if not message.from_user or message.from_user.id not in pending_tag_users:
        return
    if not is_admin(message.from_user.id):
        return
    raw_value = message.text or message.caption or ""
    value = raw_value.strip()
    if not value:
        await message.answer("تگ خالی است؛ دوباره ارسال کن.")
        return
    leading = len(raw_value) - len(raw_value.lstrip())
    leading_utf16 = _utf16_len(raw_value[:leading])
    value = raw_value.strip()
    TAG_TEXT = value
    TAG_ENTITIES = []
    for entity in (message.entities or message.caption_entities or []):
        if entity.type == "custom_emoji" and entity.custom_emoji_id:
            adjusted_offset = entity.offset - leading_utf16
            if adjusted_offset >= 0 and adjusted_offset + entity.length <= _utf16_len(value):
                TAG_ENTITIES.append({
                    "type": "custom_emoji", "offset": adjusted_offset,
                    "length": entity.length, "custom_emoji_id": entity.custom_emoji_id,
                })
    save_runtime_config()
    pending_tag_users.discard(message.from_user.id)
    await message.answer("تگ ذخیره شد. ایموجی‌های سفارشی‌ای که همراه پیام ارسال شده باشند نیز ثبت شدند.")

def load_seen():
    global seen_ids
    try:
        if SEEN_FILE.exists():
            seen_ids = {str(x) for x in json.loads(SEEN_FILE.read_text(encoding="utf-8"))}
    except Exception:
        log.exception("Could not load seen post IDs")

def save_seen():
    try:
        SEEN_FILE.write_text(json.dumps(sorted(seen_ids)), encoding="utf-8")
    except Exception:
        log.exception("Could not save seen post IDs")

def remove_emojis(text: str) -> str:
    # Remove common emoji, pictographs, flags, and variation selectors.
    emoji_pattern = re.compile(
        "["
        "\U0001F1E6-\U0001F1FF"
        "\U0001F300-\U0001FAFF"
        "\U00002600-\U000027BF"
        "\U0000FE0F"
        "\U0000200D"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text)


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        if re.search(r"(?:منبع|source)\s*[:：]", line, re.I):
            continue
        if re.search(r"https?://t\.me/(?:HoopoeAr|rasedpersian)\b", line, re.I):
            continue
        lines.append(line)
    return "\n".join(lines).strip()

def add_tag(text: str) -> str:
    """Append the configured channel tag once; premium custom emoji IDs need separate entities."""
    text = (text or "").strip()
    tag = TAG_TEXT
    if not tag:
        return text
    if tag in text:
        return text
    return f"{text}\n\n{tag}" if text else tag


def _utf16_len(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2

def quote_entities(text: str):
    """Create Telegram entities for the Premium user session (not Bot API)."""
    if not TAG_TEXT or not text:
        return None
    start = text.rfind(TAG_TEXT)
    if start < 0:
        return None
    offset = _utf16_len(text[:start])
    entities = [tl_types.MessageEntityBlockquote(offset=offset, length=_utf16_len(TAG_TEXT))]
    for item in TAG_ENTITIES:
        entities.append(tl_types.MessageEntityCustomEmoji(
            offset=offset + int(item["offset"]), length=int(item["length"]),
            document_id=int(item["custom_emoji_id"]),
        ))
    return entities


async def react_heart(message_id: int):
    """Add a heart reaction to a published channel message (bot must be channel admin)."""
    try:
        await bot.set_message_reaction(
            chat_id=TARGET_CHANNEL,
            message_id=message_id,
            reaction=[ReactionTypeEmoji(emoji="❤️")],
        )
    except Exception:
        log.exception("Could not add heart reaction to target message %s; check bot admin/reaction permissions", message_id)


async def publish_text(text: str):
    """Publish text using the connected Premium Telegram account."""
    full_text = add_tag(text)
    sent_messages = []
    for chunk in split_text(full_text):
        sent = await client.send_message(
            TARGET_CHANNEL, chunk, formatting_entities=quote_entities(chunk), link_preview=False
        )
        await react_heart(sent.id)
        sent_messages.append(sent)
    return sent_messages


def split_text(text: str, limit: int = 4000):
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        yield text[:cut].strip()
        text = text[cut:].strip()
    if text:
        yield text

def _libretranslate_request(text: str) -> str:
    payload = {
        "q": text,
        "source": "auto",
        "target": "fa",
        "format": "text",
    }
    if LIBRETRANSLATE_API_KEY:
        payload["api_key"] = LIBRETRANSLATE_API_KEY
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        LIBRETRANSLATE_URL,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body.get("translatedText", "")


async def translate_text(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    last_error = None
    for attempt in range(5):
        try:
            result = await asyncio.to_thread(_libretranslate_request, text)
            result = clean_text(result or "")
            if not result and TRANSLATE_REQUIRED:
                raise RuntimeError("LibreTranslate returned an empty result")
            return result
        except Exception as exc:
            last_error = exc
            if attempt < 4:
                wait_seconds = min(2 ** attempt, 16)
                log.warning("LibreTranslate attempt %s/5 failed; retrying in %s seconds: %s",
                            attempt + 1, wait_seconds, exc)
                await asyncio.sleep(wait_seconds)
    raise RuntimeError(f"LibreTranslate failed after 5 attempts: {last_error}") from last_error

async def send_translated_message(message, source_key: str):
    post_key = f"{source_key}:{message.id}"
    if post_key in seen_ids or str(message.id) in seen_ids:
        return
    original = clean_text(message.message or "")
    translated = ""
    if original:
        try:
            translated = await translate_text(original)
        except Exception:
            log.exception("Translation failed for message %s", message.id)
            if TRANSLATE_REQUIRED:
                return
            translated = original

    full_caption = add_tag(translated)
    caption = full_caption[:1024] if full_caption else None
    caption_entities = quote_entities(caption or "")
    remainder = full_caption[1024:].strip() if len(full_caption) > 1024 else ""
    media_path = None
    try:
        sent_messages = []
        if message.media:
            mime = (getattr(message.file, "mime_type", "") or "").lower() if message.file else ""
            suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                      "video/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/ogg": ".ogg"}.get(mime, "")
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                media_path = tmp.name
            downloaded = await message.download_media(file=media_path)
            if downloaded:
                sent = await client.send_file(
                    TARGET_CHANNEL, downloaded, caption=caption or "",
                    formatting_entities=quote_entities(caption or ""),
                    supports_streaming=mime.startswith("video/"),
                )
                sent_messages.extend(sent if isinstance(sent, list) else [sent])
            else:
                log.error("Could not download media for source message %s", message.id)
                return
        else:
            # Text-only posts get the same tag and quote formatting as media captions.
            await publish_text(translated) if translated else await publish_text("")

        for sent in sent_messages:
            await react_heart(sent.id)
        if remainder:
            for chunk in split_text(remainder):
                sent = await client.send_message(TARGET_CHANNEL, chunk, link_preview=False)
                await react_heart(sent.id)
        seen_ids.add(post_key)
        save_seen()
        log.info("Relayed message %s", message.id)
    except Exception:
        log.exception("Failed to relay message %s", message.id)
    finally:
        if media_path:
            try:
                Path(media_path).unlink(missing_ok=True)
            except Exception:
                pass

async def send_translated_album(messages, source_key: str):
    """Send a Telegram media group with translated caption, quoted tag and heart reaction."""
    if not messages:
        return
    messages = sorted(messages, key=lambda item: item.id)
    album_key = f"{source_key}:album:{messages[0].grouped_id or messages[0].id}"
    if album_key in seen_ids:
        return

    original = ""
    for item in messages:
        if item.message:
            original = clean_text(item.message)
            if original:
                break
    translated = ""
    if original:
        try:
            translated = await translate_text(original)
        except Exception:
            log.exception("Album translation failed for %s", album_key)
            if TRANSLATE_REQUIRED:
                return

    media_items, paths = [], []
    try:
        full_caption = add_tag(translated)
        caption = full_caption[:1024] if full_caption else None
        entities = quote_entities(caption or "")
        for index, item in enumerate(messages):
            if not item.media:
                continue
            mime = (getattr(item.file, "mime_type", "") or "").lower() if item.file else ""
            suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4"}.get(mime, ".bin")
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                path = tmp.name
            paths.append(path)
            downloaded = await item.download_media(file=path)
            if not downloaded:
                log.error("Could not download album media item %s", item.id)
                return
            upload = FSInputFile(downloaded)
            item_caption = caption if not media_items else None
            item_entities = entities if not media_items else None
            if mime.startswith("video/"):
                media_items.append(InputMediaVideo(media=upload, caption=item_caption, caption_entities=item_entities, supports_streaming=True))
            elif mime.startswith("image/"):
                media_items.append(InputMediaPhoto(media=upload, caption=item_caption, caption_entities=item_entities))
            else:
                media_items.append(InputMediaDocument(media=upload, caption=item_caption, caption_entities=item_entities))

        sent_messages = []
        if paths:
            sent = await client.send_file(
                TARGET_CHANNEL, paths, caption=caption or "",
                formatting_entities=entities, supports_streaming=True,
            )
            sent_messages = sent if isinstance(sent, list) else [sent]
        else:
            await publish_text(translated)

        # Heart reaction is added to every message in the album.
        for sent in sent_messages:
            await react_heart(sent.id)
        remainder = full_caption[1024:].strip() if len(full_caption) > 1024 else ""
        if remainder:
            for chunk in split_text(remainder):
                sent = await client.send_message(TARGET_CHANNEL, chunk, link_preview=False)
                await react_heart(sent.id)

        seen_ids.add(album_key)
        for item in messages:
            seen_ids.add(f"{source_key}:{item.id}")
        save_seen()
        log.info("Relayed album %s (%s items)", album_key, len(media_items))
    except Exception:
        log.exception("Failed to relay album %s", album_key)
    finally:
        for path in paths:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


async def main():
    load_seen()
    load_runtime_config()
    await client.start()
    me = await client.get_me()
    log.info("Telethon connected as %s", getattr(me, "username", None) or me.id)
    sources = []
    for source_name in SOURCE_CHANNELS:
        try:
            entity = await client.get_entity(source_name)
            sources.append((source_name, entity))
            log.info("Watching @%s -> %s", source_name, TARGET_CHANNEL)
        except Exception:
            log.exception("Could not access source channel @%s", source_name)

    if not sources:
        raise RuntimeError("No source channels could be opened. Check SOURCE_CHANNELS and account membership.")

    source_entities = [entity for _, entity in sources]
    log.info("Active source channels (%s): %s", len(sources), ", ".join("@" + name for name, _ in sources))

    @client.on(events.Album(chats=source_entities))
    async def on_album(event):
        await send_translated_album(event.messages, str(event.chat_id))

    @client.on(events.NewMessage(chats=source_entities))
    async def on_new_message(event):
        # Telegram sends each album item as a NewMessage too; the Album handler
        # publishes the group together, so skip individual album items here.
        if getattr(event.message, "grouped_id", None):
            return
        await send_translated_message(event.message, str(event.chat_id))

    if CATCHUP_LIMIT:
        for source_name, source in sources:
            source_key = str(getattr(source, "id", source_name))
            for message in reversed(await client.get_messages(source, limit=CATCHUP_LIMIT)):
                post_key = f"{source_key}:{message.id}"
                if post_key not in seen_ids and str(message.id) not in seen_ids:
                    await send_translated_message(message, source_key)
    # Run the Bot API panel alongside the Telethon user-session listener.
    polling_task = asyncio.create_task(dp.start_polling(bot, handle_signals=False))
    log.info("Bot admin panel polling started; send /panel to the bot")
    try:
        await client.run_until_disconnected()
    finally:
        polling_task.cancel()
        await asyncio.gather(polling_task, return_exceptions=True)

if __name__ == "__main__":
    asyncio.run(main())
