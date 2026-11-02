# Telegram News Translator V4 — source channels configured

Default source channels:
- @rasedal3ado138e
- @SolIalIe

Target: @rasedpersian

Railway Variables (set explicitly; SOURCE_CHANNELS overrides the default):
- SOURCE_CHANNELS=rasedal3ado138e,SolIalIe
- TARGET_CHANNEL=@rasedpersian
- Start command: python main.py

The Telethon account identified by SESSION_STRING must be able to access both source channels. The Bot API bot must be an admin in the target channel with permission to post and manage reactions. Set ADMIN_IDS to your numeric Telegram user ID to restrict the panel; /panel opens the panel.
