#!/usr/bin/env python3
"""
Read-only CardDAV client for iCloud Contacts.
Usage:
  contacts.py list [--limit N]
  contacts.py search QUERY [--limit N]
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from base64 import b64encode

CARDDAV_URL = "https://contacts.icloud.com"

NS = {
    "d": "DAV:",
    "card": "urn:ietf:params:xml:ns:carddav",
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
    """Discover the user's principal URL."""
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
    status, resp = request("PROPFIND", CARDDAV_URL + "/", headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Discovery failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    href = root.find(".//d:current-user-principal/d:href", NS)
    if href is None:
        print(json.dumps({"error": "Could not find principal URL"}))
        sys.exit(1)
    return href.text.strip()


def discover_addressbook_home(apple_id, app_password, principal_url):
    """Discover the addressbook home set URL."""
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "0",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <card:addressbook-home-set/>
  </d:prop>
</d:propfind>"""
    base = CARDDAV_URL if not principal_url.startswith("http") else ""
    status, resp = request("PROPFIND", base + principal_url, headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Addressbook home discovery failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    href = root.find(".//{urn:ietf:params:xml:ns:carddav}addressbook-home-set/{DAV:}href")
    if href is None:
        print(json.dumps({"error": "Could not find addressbook-home-set"}))
        sys.exit(1)
    return href.text.strip()


def discover_addressbook(apple_id, app_password, home_url):
    """Discover the default address book URL within the home set."""
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "1",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <d:resourcetype/>
    <d:displayname/>
  </d:prop>
</d:propfind>"""
    status, resp = request("PROPFIND", home_url, headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Address book discovery failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    for response in root.findall(".//d:response", NS):
        resourcetype = response.find(".//d:resourcetype", NS)
        if resourcetype is not None and resourcetype.find("card:addressbook", NS) is not None:
            href = response.find("d:href", NS)
            if href is not None:
                return href.text.strip()
    print(json.dumps({"error": "No address book found"}))
    sys.exit(1)


def fetch_contacts(apple_id, app_password, addressbook_url):
    """Fetch all vCards from the address book."""
    headers = {
        **auth_header(apple_id, app_password),
        "Content-Type": "application/xml",
        "Depth": "1",
    }
    body = """<?xml version="1.0" encoding="utf-8"?>
<card:addressbook-query xmlns:d="DAV:" xmlns:card="urn:ietf:params:xml:ns:carddav">
  <d:prop>
    <d:getetag/>
    <card:address-data/>
  </d:prop>
</card:addressbook-query>"""
    base = CARDDAV_URL if not addressbook_url.startswith("http") else ""
    status, resp = request("REPORT", base + addressbook_url, headers, body)
    if status not in (207, 200):
        print(json.dumps({"error": f"Fetch contacts failed: HTTP {status}"}))
        sys.exit(1)
    root = ET.fromstring(resp)
    vcards = []
    for response in root.findall(".//d:response", NS):
        addr_data = response.find(".//card:address-data", NS)
        if addr_data is not None and addr_data.text:
            vcards.append(addr_data.text)
    return vcards


def parse_vcard(vcard_text):
    """Parse a vCard string into a simple dict."""
    contact = {
        "name": "", "last_name": "", "first_name": "", "middle_name": "",
        "company": "", "title": "", "birthday": "",
        "phones": [], "emails": [], "addresses": [], "note": "",
    }
    for line in vcard_text.splitlines():
        line = line.strip()
        upper = line.upper()
        if upper.startswith("FN:"):
            contact["name"] = line[3:].strip()
        elif upper.startswith("N:"):
            parts = line[2:].split(";")
            contact["last_name"] = parts[0].strip() if len(parts) > 0 else ""
            contact["first_name"] = parts[1].strip() if len(parts) > 1 else ""
            contact["middle_name"] = parts[2].strip() if len(parts) > 2 else ""
        elif upper.startswith("ORG:") and ":" in line:
            contact["company"] = line.split(":", 1)[1].split(";")[0].strip()
        elif upper.startswith("TITLE:"):
            contact["title"] = line[6:].strip()
        elif upper.startswith("BDAY:") or upper.startswith("BDAY;"):
            contact["birthday"] = line.split(":", 1)[1].strip() if ":" in line else ""
        elif upper.startswith("NOTE:"):
            val = line[5:].strip()
            if val and not val.startswith("z") and len(val) < 500:
                contact["note"] = val
        elif "TEL" in upper and ":" in line:
            phone = line.split(":", 1)[1].strip()
            if phone:
                contact["phones"].append(phone)
        elif "EMAIL" in upper and ":" in line and "ENCODING" not in upper:
            email = line.split(":", 1)[1].strip()
            if email:
                contact["emails"].append(email)
        elif upper.startswith("ADR") and ":" in line:
            parts = line.split(":", 1)[1].split(";")
            addr = ", ".join(p.strip() for p in parts if p.strip())
            if addr:
                contact["addresses"].append(addr)
    if not contact["name"]:
        contact["name"] = " ".join(p for p in [contact["first_name"], contact["middle_name"], contact["last_name"]] if p)
    return contact


def matches_query(contact, query):
    query = query.lower()
    for field in ("name", "last_name", "first_name", "middle_name", "company", "title", "note"):
        if query in contact.get(field, "").lower():
            return True
    if any(query in p.lower() for p in contact["phones"]):
        return True
    if any(query in e.lower() for e in contact["emails"]):
        return True
    if any(query in a.lower() for a in contact["addresses"]):
        return True
    return False


def cmd_list(args):
    apple_id, app_password = get_credentials()
    principal = discover_principal(apple_id, app_password)
    home_url = discover_addressbook_home(apple_id, app_password, principal)
    ab_url = discover_addressbook(apple_id, app_password, home_url)
    vcards = fetch_contacts(apple_id, app_password, ab_url)
    contacts = [parse_vcard(v) for v in vcards]
    contacts = [c for c in contacts if c["name"]]
    contacts = sorted(contacts, key=lambda c: c["name"].lower())
    if args.limit:
        contacts = contacts[: args.limit]
    print(json.dumps(contacts, ensure_ascii=False, indent=2))


def cmd_search(args):
    apple_id, app_password = get_credentials()
    principal = discover_principal(apple_id, app_password)
    home_url = discover_addressbook_home(apple_id, app_password, principal)
    ab_url = discover_addressbook(apple_id, app_password, home_url)
    vcards = fetch_contacts(apple_id, app_password, ab_url)
    contacts = [parse_vcard(v) for v in vcards]
    results = [c for c in contacts if matches_query(c, args.query)]
    if args.limit:
        results = results[: args.limit]
    print(json.dumps(results, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Read-only iCloud Contacts via CardDAV")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List all contacts")
    p_list.add_argument("--limit", type=int, default=None, help="Max number of results")

    p_search = sub.add_parser("search", help="Search contacts by name, phone, or email")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--limit", type=int, default=50, help="Max number of results (default: 50)")

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "search":
        cmd_search(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
