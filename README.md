# Telegram News Translator (Quote + Heart)

Railway deployment files. Keep your existing Railway Variables: API_ID, API_HASH, SESSION_STRING, BOT_TOKEN, SOURCE_CHANNELS, TARGET_CHANNEL, TAG_TEXT, LIBRETRANSLATE_URL, LIBRETRANSLATE_API_KEY, TRANSLATE_REQUIRED, DATA_DIR.

The bot appends TAG_TEXT with a real blank line, formats the tag as a Telegram blockquote, preserves source emoji in text, and attempts to add a ❤️ reaction to each published message.

Important: add BOT_TOKEN bot as an administrator in TARGET_CHANNEL and allow it to manage reactions. Telegram may reject reactions if this permission is missing or channel reactions are disabled.

Set Railway Start Command to `python main.py` (or use the included Procfile). Do not use `main.pyn`.
