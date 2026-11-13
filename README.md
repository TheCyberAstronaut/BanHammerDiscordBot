# Discord Ban Hammer Bot

Discord bot for email verification and message reporting with admin review.

## Features
- Email verification via SMTP (optional)
- Role-gated `/report` command
- Admin review workflow with approve/deny buttons
- Wall of shame posting with link defanging
- SQLite storage
- Docker-ready

## Requirements
- Python 3.12+
- Discord application and bot token
- SMTP server (if email verification enabled)
- Docker (optional)

## Configuration
Copy `.env.example` to `.env` and fill values.

Required env vars:
- `DISCORD_TOKEN`
- `ADMIN_CHANNEL_ID`
- `WALL_OF_SHAME_CHANNEL_ID`
- `VERIFIED_ROLE_ID`
- `REPORT_ROLE_ALLOWLIST`

Email verification (optional):
- `EMAIL_VERIFICATION_ENABLED` (default `true`)
- `SMTP_HOST`
- `SMTP_PORT` (default `587`)
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_USE_TLS` (default `true`)
- `EMAIL_FROM`
- `VERIFICATION_DOMAIN_ALLOWLIST` (comma-separated)
- `VERIFICATION_DOMAIN_DENYLIST` (comma-separated)
- `VERIFICATION_TOKEN_TTL_MINUTES` (default `30`)

Storage and logging:
- `DB_PATH` (default `data/bot.db`)
- `LOG_LEVEL` (default `INFO`)

### Role allowlist behavior
`REPORT_ROLE_ALLOWLIST` is a comma-separated list of role IDs.
If empty or missing, `/report` is disabled for everyone.

Example:
```
REPORT_ROLE_ALLOWLIST=123456789012345678,987654321098765432
```

## Discord setup
1. Create a Discord application and bot in the Developer Portal.
2. Enable Message Content Intent for the bot.
3. Invite the bot with these scopes:
   - `bot`
   - `applications.commands`
4. Grant permissions:
   - Manage Messages (for approvals)
   - Read Message History
   - Send Messages
   - Manage Roles (for verification role)
   - Ban Members (optional, if you want to ban users after approval)

### Intents and permission checks
Required intents in the Developer Portal:
- Server Members Intent (role checks and assignment)
- Message Content Intent (reading reported message content)

Runtime permission checks:
- The bot checks for admin-level permissions on report approve/deny actions.
- The bot must have Manage Roles to assign the verification role.
- If Manage Messages is missing, approvals will still post to the wall of shame, but the original message will remain.

Recommended channel permissions:
- Admin channel: bot can Send Messages and Use Application Commands.
- Wall of shame: bot can Send Messages and Embed Links.

## Run locally
```
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

## Run with Docker
```
docker build -t discord-ban-hammer .
docker run --env-file .env -v $(pwd)/data:/app/data discord-ban-hammer
```

## Slash commands
Verification (if enabled):
- `/verify_start <email>`
- `/verify_confirm <code>`
- `/verify_status`
- `/verify_resend`

Reporting:
- `/report <message_link> <reason>`

## Behavior notes
- Messages are only deleted after admin approval.
- If deletion fails, the wall-of-shame post still happens and the report is marked approved.
- If verification is disabled, verification commands are unavailable.

## Extending
- Add new cogs in `bot/cogs/`
- Add services in `bot/` and wire them in `bot/main.py`

## Authors
- Don Cowan
- Matthew Hancock