# icloud-readonly

Read-only OpenClaw skill for iCloud Contacts and Calendar.

- **Contacts** — list and search via CardDAV
- **Calendar** — list calendars and fetch events via CalDAV
- **No dependencies** — stdlib Python only
- **Read-only by design** — no write operations implemented

## Install

Paste the repo URL into OpenClaw chat:

```
Install skill from https://github.com/muxadil/skill_icloud
```

## Setup

Generate an app-specific password at [appleid.apple.com](https://appleid.apple.com) → Sign-In and Security → App-Specific Passwords.

Set environment variables on your machine:

```bash
export APPLE_ID="you@icloud.com"
export APPLE_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

## Usage

After install, invoke with `/icloud-readonly` or ask the agent directly:

- "Find John's phone number"
- "What's on my calendar this week?"
- "Show my calendars"

## Commands

**Contacts:**
```bash
python3 scripts/contacts.py list
python3 scripts/contacts.py list --limit 20
python3 scripts/contacts.py search "John"
python3 scripts/contacts.py search "john@example.com" --limit 10
```

**Calendar:**
```bash
python3 scripts/calendars.py list
python3 scripts/calendars.py events --days 7
python3 scripts/calendars.py events --from 2026-04-01 --to 2026-04-30
```

## Security

- Credentials only from environment variables — never stored or logged
- Only `GET`, `PROPFIND`, `REPORT` HTTP methods — no writes
- Requests go to `caldav.icloud.com` and `contacts.icloud.com` only
- Agent is restricted to these two scripts via `allowed-tools`
