# Telegram News Translator — Panel V4

Railway worker with Telethon source listener and an aiogram admin panel.

Required Railway variables:
- API_ID, API_HASH, SESSION_STRING, BOT_TOKEN
- SOURCE_CHANNELS — comma-separated, e.g. `rasedal3ado138e,kataebAlqasam`
- TARGET_CHANNEL — e.g. `@rasedpersian`
- LIBRETRANSLATE_URL and optionally LIBRETRANSLATE_API_KEY
- ADMIN_IDS — numeric Telegram user ID(s), comma-separated (recommended)
- TAG_TEXT — optional initial tag

Open a private chat with the bot and send `/panel`. Choose “تنظیم تگ”, then send the tag as one message. Premium custom emoji entities in that message are saved in `bot_config.json`.

Add the Telethon account (SESSION_STRING) to both source channels. Add the bot as an administrator in the target channel with permission to post and manage reactions. Set SOURCE_CHANNELS to both desired usernames separated by a comma. Railway variables override code defaults.

Railway ephemeral storage may reset bot_config.json on redeploy; use a Railway Volume and set DATA_DIR to its mount path for persistence.
