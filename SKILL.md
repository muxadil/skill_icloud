---
name: icloud-readonly
description: Read-only access to iCloud Contacts and Calendar. Use when the user wants to find contacts, look up phone numbers or emails, check calendar events, or view their schedule. Requires APPLE_ID and APPLE_APP_PASSWORD environment variables.
disable-model-invocation: true
allowed-tools: Bash(python3 {baseDir}/scripts/contacts.py *), Bash(python3 {baseDir}/scripts/calendars.py *)
metadata: {"openclaw":{"emoji":"☁️","requires":{"env":["APPLE_ID","APPLE_APP_PASSWORD"]},"primaryEnv":"APPLE_ID"}}
---

# iCloud Read-Only

Read contacts and calendar events from iCloud via CardDAV and CalDAV protocols.
No write operations. No third-party dependencies — stdlib Python only.

## Credentials

Set these environment variables on the VM:

```bash
export APPLE_ID="you@icloud.com"
export APPLE_APP_PASSWORD="xxxx-xxxx-xxxx-xxxx"
```

Generate an app-specific password at appleid.apple.com → Sign-In and Security → App-Specific Passwords.

## Contacts

```bash
python3 {baseDir}/scripts/contacts.py list
python3 {baseDir}/scripts/contacts.py search "John"
python3 {baseDir}/scripts/contacts.py search "john@example.com"
```

Output is JSON:
```json
[{"name": "John Doe", "phones": ["+1234567890"], "emails": ["john@example.com"]}]
```

## Calendar

```bash
python3 {baseDir}/scripts/calendars.py list
python3 {baseDir}/scripts/calendars.py events --from 2026-04-01 --to 2026-04-07
python3 {baseDir}/scripts/calendars.py events --days 7
```

Output is JSON:
```json
[{"title": "Team Meeting", "start": "2026-04-01T10:00:00", "end": "2026-04-01T11:00:00", "calendar": "Work"}]
```

## Security

- Credentials read from env only — never logged or stored
- Only GET/PROPFIND/REPORT HTTP methods — no write operations
- All requests go to Apple servers over HTTPS only
- Agent can only invoke these two scripts — no arbitrary bash
