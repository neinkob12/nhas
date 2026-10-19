#!/usr/bin/env python3
"""Watch Nhas City Chicken dine-in time slots and reserve (hold) one as soon as it is free.

The ordering site (https://citychickennhas.de/bestellen/en/koeln) is a Next.js app that
talks to a small JSON API under /bestellen/api. This script uses the same endpoints:

    GET  /me                                    -> who is logged in
    GET  /store/<slug>?locale=en                -> store info (we need its "id")
    GET  /slots?store=<id>&date=YYYY-MM-DD&party=N&locale=en
                                                -> {date, today, bookableDates, rules, slots:[...]}
    POST /holds {store, scheduledAt, partySize} -> reserves the slot for ~10 minutes

Authentication is your browser session cookie (see README.md). Only the Python
standard library is used, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE = "https://citychickennhas.de"
API = f"{BASE}/bestellen/api"
TZ = ZoneInfo("Europe/Berlin")
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/141.0 Safari/537.36"
)


class ApiError(Exception):
    def __init__(self, status: int, code: str, details: dict | None = None):
        super().__init__(f"HTTP {status} {code} {details or ''}".strip())
        self.status = status
        self.code = code
        self.details = details or {}


class Client:
    def __init__(self, cookie: str, locale: str, timeout: float = 20):
        self.cookie = cookie
        self.locale = locale
        self.timeout = timeout

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None):
        url = f"{API}{path}"
        if query:
            url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
        headers = {
            "Accept": "application/json",
            "Cookie": self.cookie,
            "User-Agent": USER_AGENT,
            "Referer": f"{BASE}/bestellen/{self.locale}/",
            "Origin": BASE,
        }
        data = None
        if method != "GET":
            headers["Content-Type"] = "application/json"
            data = json.dumps(body or {}).encode()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                err = json.loads(raw).get("error", {})
            except (ValueError, AttributeError):
                err = {}
            raise ApiError(e.code, err.get("code", "HTTP_ERROR"), err.get("details")) from None

    def me(self):
        return self.request("GET", "/me")

    def store(self, slug: str):
        return self.request("GET", f"/store/{slug}", {"locale": self.locale})

    def slots(self, store_id: str, day: str, party: int):
        return self.request(
            "GET",
            "/slots",
            {"store": store_id, "date": day, "party": party, "locale": self.locale, "fresh": 1},
        )

    def current_hold(self):
        return self.request("GET", "/holds")

    def hold(self, store_id: str, scheduled_at: str, party: int):
        return self.request(
            "POST", "/holds", body={"store": store_id, "scheduledAt": scheduled_at, "partySize": party}
        )


@dataclass
class Filters:
    party: int
    dates: list[str] | None  # None = any bookable date
    earliest: dtime | None
    latest: dtime | None
    max_days_ahead: int


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(TZ)


def log(msg: str) -> None:
    print(f"[{datetime.now(TZ):%H:%M:%S}] {msg}", flush=True)


def slot_ok(slot: dict, f: Filters, min_lead_minutes: int) -> bool:
    """Mirror the site's own rule: bookable, enough room, not too soon, inside our window."""
    if not slot.get("bookable"):
        return False
    if (slot.get("remainingPersons") or 0) < f.party:
        return False
    start = parse_ts(slot["start"])
    if start < datetime.now(TZ) + timedelta(minutes=min_lead_minutes):
        return False
    if f.earliest and start.time() < f.earliest:
        return False
    if f.latest and start.time() > f.latest:
        return False
    return True


def find_slot(client: Client, store_id: str, f: Filters) -> dict | None:
    """Return the earliest matching free slot across the wanted dates, or None."""
    first = client.slots(store_id, f.dates[0] if f.dates else datetime.now(TZ).date().isoformat(), f.party)
    bookable = first.get("bookableDates") or []
    if f.dates:
        days = [d for d in f.dates if not bookable or d in bookable]
    else:
        limit = (date.fromisoformat(first.get("today") or date.today().isoformat())
                 + timedelta(days=f.max_days_ahead)).isoformat()
        days = [d for d in bookable if d <= limit]

    for day in days:
        data = first if first.get("date") == day else client.slots(store_id, day, f.party)
        lead = (data.get("rules") or {}).get("minLeadMinutes") or 0
        free = [s for s in data.get("slots") or [] if slot_ok(s, f, lead)]
        log(f"{day}: {len(free)} matching slot(s) out of {len(data.get('slots') or [])}")
        if free:
            return min(free, key=lambda s: s["start"])
    return None


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cookie", help="Cookie header value (default: $NHAS_COOKIE or --cookie-file)")
    p.add_argument("--cookie-file", default="cookie.txt", help="File holding the Cookie header (default: cookie.txt)")
    p.add_argument("--store", default="koeln", help="Store slug from the URL (default: koeln)")
    p.add_argument("--locale", default="en")
    p.add_argument("--party", type=int, default=2, help="Number of people (default: 2)")
    p.add_argument("--date", action="append", dest="dates", metavar="YYYY-MM-DD",
                   help="Only these dates (repeatable). Default: any bookable date")
    p.add_argument("--days-ahead", type=int, default=7, help="When no --date given, look this many days ahead (default: 7)")
    p.add_argument("--earliest", type=dtime.fromisoformat, help="Earliest start time, e.g. 18:00")
    p.add_argument("--latest", type=dtime.fromisoformat, help="Latest start time, e.g. 20:30")
    p.add_argument("--interval", type=float, default=30, help="Seconds between checks (default: 30)")
    p.add_argument("--once", action="store_true", help="Check once and exit instead of polling")
    p.add_argument("--dry-run", action="store_true", help="Only report free slots, never reserve")
    return p.parse_args(argv)


def load_cookie(args: argparse.Namespace) -> str:
    cookie = args.cookie or os.environ.get("NHAS_COOKIE")
    if not cookie and os.path.exists(args.cookie_file):
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookie = fh.read().strip()
    if not cookie:
        sys.exit("No cookie found. Put your browser's Cookie header in cookie.txt (see README.md).")
    return cookie.removeprefix("Cookie:").strip()


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    client = Client(load_cookie(args), args.locale)
    filters = Filters(args.party, args.dates, args.earliest, args.latest, args.days_ahead)

    try:
        me = client.me()
    except ApiError as e:
        if e.status == 401:
            sys.exit("Not logged in: the cookie is missing or expired. Copy a fresh one from your browser.")
        raise
    log(f"Logged in as {me.get('email') or me.get('name') or me.get('id') or 'unknown user'}")

    store = client.store(args.store)
    store_id = store["id"]
    log(f"Store {args.store!r} -> id {store_id}")

    while True:
        wait = args.interval
        try:
            slot = find_slot(client, store_id, filters)
            if slot is None:
                log("No matching slot free yet.")
            elif args.dry_run:
                log(f"Free: {parse_ts(slot['start']):%a %d.%m %H:%M} ({slot['remainingPersons']} places left). Dry run, not reserving.")
                return 0
            else:
                start = parse_ts(slot["start"])
                log(f"Reserving {start:%a %d.%m %H:%M} for {args.party} ...")
                try:
                    hold = client.hold(store_id, slot["start"], args.party)
                except ApiError as e:
                    if e.code == "SLOT_FULL":
                        log("Someone was faster, slot is full now. Retrying.")
                        wait = 1
                    else:
                        raise
                else:
                    expires = hold.get("expiresAt")
                    until = f" until {parse_ts(expires):%H:%M}" if expires else ""
                    log(f"RESERVED {start:%a %d.%m %H:%M} for {args.party}{until}.")
                    log(f"Finish your order in the browser now: {BASE}/bestellen/{args.locale}/{args.store}")
                    return 0
        except ApiError as e:
            if e.status == 401:
                log("Session expired. Copy a fresh cookie from your browser.")
                return 1
            if e.code == "RATE_LIMITED":
                wait = max(wait, float(e.details.get("retryAfter") or 60))
                log(f"Rate limited, waiting {wait:.0f}s.")
            elif e.code in {"PHONE_NOT_VERIFIED", "TERMS_UPDATE_REQUIRED", "PAYMENT_IN_PROGRESS"} or e.status in (400, 403, 409, 422):
                log(f"Cannot reserve: {e}. Fix this in the browser, then run again.")
                return 1
            else:
                log(f"API error: {e}")
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log(f"Network error: {e}")

        if args.once:
            return 0 if args.dry_run else 2
        time.sleep(wait + random.uniform(0, wait * 0.2))


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
