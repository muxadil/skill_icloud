#!/usr/bin/env python3
"""
Read-only CalDAV client for iCloud Calendar.
Usage:
  calendars.py list
  calendars.py events --days N
  calendars.py events --from YYYY-MM-DD --to YYYY-MM-DD
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from base64 import b64encode
from datetime import datetime, timedelta, timezone

CALDAV_URL = "https://caldav.icloud.com"

NS = {
    "d": "DAV:",
    "cal": "urn:ietf:params:xml:ns:caldav",
    "cs": "http://calendarserver.org/ns/",
    "ical": "http://apple.com/ns/ical/",
}


def _load_env_file(path="/home/openclaw/.icloud.env"):
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def get_credentials():
    _load_env_file()
    apple_id = os.environ.get("APPLE_ID", "").strip()
    app_password = os.environ.get("APPLE_APP_TOKEN", os.environ.get("APPLE_APP_PASSWORD", "")).strip()
    if not apple_id or not app_password:
        print(json.dumps({"error": "APPLE_ID and APPLE_APP_TOKEN env variables are required"}))
        sys.exit(1)
    return apple_id, app_password


def auth_header(apple_id, app_password):
    token = b64encode(f"{apple_id}:{app_password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def request(method, url, headers, body=None):
    req = urllib.request.Request(url, method=method, headers=headers)
    if body:
        req.data = body.encode("utf-8")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def discover_principal(apple_id, app_password):
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "0",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:current-user-principal/>
  </d:prop>
</d:propfind>"""
    status, resp = request("PROPFIND", CALDAV_URL + "/", headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Discovery failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    href = root.find(".//d:current-user-principal/d:href", NS)
    if href is None:
        print(json.dumps({"error": "Could not find principal URL"}))
        sys.exit(1)
    return href.text.strip()


def discover_calendar_home(apple_id, app_password, principal_url):
    """Discover the calendar home set URL."""
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "0",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <cal:calendar-home-set/>
  </d:prop>
</d:propfind>"""
    base = CALDAV_URL if not principal_url.startswith("http") else ""
    status, resp = request("PROPFIND", base + principal_url, headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Calendar home discovery failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    href = root.find(".//{urn:ietf:params:xml:ns:caldav}calendar-home-set/{DAV:}href")
    if href is None:
        print(json.dumps({"error": "Could not find calendar-home-set"}))
        sys.exit(1)
    return href.text.strip()


def discover_calendars(apple_id, app_password, home_url):
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "1",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav" xmlns:ical="http://apple.com/ns/ical/">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
    <ical:calendar-color/>
  </d:prop>
</d:propfind>"""
    status, resp = request("PROPFIND", home_url, headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Calendar discovery failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    calendars = []
    for response in root.findall(".//d:response", NS):
        resourcetype = response.find(".//d:resourcetype", NS)
        if resourcetype is not None and resourcetype.find("cal:calendar", NS) is not None:
            href = response.find("d:href", NS)
            name = response.find(".//d:displayname", NS)
            if href is not None:
                calendars.append({
                    "url": href.text.strip(),
                    "name": name.text.strip() if name is not None and name.text else "Unnamed",
                })
    return calendars


def fetch_events(apple_id, app_password, calendar_url, date_from, date_to):
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "1",
    }
    time_from = date_from.strftime("%Y%m%dT000000Z")
    time_to = date_to.strftime("%Y%m%dT235959Z")
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<cal:calendar-query xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:prop>
    <d:getetag/>
    <cal:calendar-data/>
  </d:prop>
  <cal:filter>
    <cal:comp-filter name="VCALENDAR">
      <cal:comp-filter name="VEVENT">
        <cal:time-range start="{time_from}" end="{time_to}"/>
      </cal:comp-filter>
    </cal:comp-filter>
  </cal:filter>
</cal:calendar-query>"""
    base = CALDAV_URL if not calendar_url.startswith("http") else ""
    status, resp = request("REPORT", base + calendar_url, headers, body)
    if status not in (207, 200):
        return []
    root = ET.fromstring(resp)
    icals = []
    for response in root.findall(".//d:response", NS):
        cal_data = response.find(".//cal:calendar-data", NS)
        if cal_data is not None and cal_data.text:
            icals.append(cal_data.text)
    return icals


def parse_ical_event(ical_text, calendar_name):
    """Parse a VEVENT from iCalendar text into a simple dict."""
    event = {"title": "", "start": "", "end": "", "location": "", "description": "", "calendar": calendar_name}
    in_vevent = False
    for line in ical_text.splitlines():
        line = line.strip()
        if line == "BEGIN:VEVENT":
            in_vevent = True
        elif line == "END:VEVENT":
            break
        elif in_vevent:
            if line.upper().startswith("SUMMARY:"):
                event["title"] = line[8:].strip()
            elif line.upper().startswith("DTSTART") and ":" in line:
                event["start"] = parse_ical_datetime(line.split(":", 1)[1].strip())
            elif line.upper().startswith("DTEND") and ":" in line:
                event["end"] = parse_ical_datetime(line.split(":", 1)[1].strip())
            elif line.upper().startswith("LOCATION:"):
                event["location"] = line[9:].strip()
            elif line.upper().startswith("DESCRIPTION:"):
                event["description"] = line[12:].strip()
    return event if event["title"] else None


def parse_ical_datetime(value):
    """Convert iCal datetime string to ISO 8601."""
    value = value.strip()
    try:
        if len(value) == 8:  # all-day: 20260401
            return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
        elif value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%dT%H:%M:%S")
        else:
            return datetime.strptime(value[:15], "%Y%m%dT%H%M%S").strftime("%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return value


def cmd_list(args):
    apple_id, app_password = get_credentials()
    principal = discover_principal(apple_id, app_password)
    home_url = discover_calendar_home(apple_id, app_password, principal)
    calendars = discover_calendars(apple_id, app_password, home_url)
    output = [{"name": c["name"]} for c in calendars]
    print(json.dumps(output, ensure_ascii=False, indent=2))


def cmd_events(args):
    apple_id, app_password = get_credentials()

    if args.days:
        date_from = datetime.now(timezone.utc)
        date_to = date_from + timedelta(days=args.days)
    else:
        try:
            date_from = datetime.strptime(args.date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            date_to = datetime.strptime(args.date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            print(json.dumps({"error": "Use --days N or --from YYYY-MM-DD --to YYYY-MM-DD"}))
            sys.exit(1)

    principal = discover_principal(apple_id, app_password)
    home_url = discover_calendar_home(apple_id, app_password, principal)
    calendars = discover_calendars(apple_id, app_password, home_url)

    all_events = []
    for cal in calendars:
        icals = fetch_events(apple_id, app_password, cal["url"], date_from, date_to)
        for ical in icals:
            event = parse_ical_event(ical, cal["name"])
            if event:
                all_events.append(event)

    all_events.sort(key=lambda e: e["start"])
    print(json.dumps(all_events, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Read-only iCloud Calendar via CalDAV")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all calendars")

    p_events = sub.add_parser("events", help="Fetch events in a date range")
    p_events.add_argument("--days", type=int, default=None, help="Next N days from today")
    p_events.add_argument("--from", dest="date_from", default=None, help="Start date YYYY-MM-DD")
    p_events.add_argument("--to", dest="date_to", default=None, help="End date YYYY-MM-DD")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "events":
        cmd_events(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
