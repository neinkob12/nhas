#!/usr/bin/env python3
"""Watch Nhas City Chicken dine-in time slots and reserve (hold) one as soon as it is free.

The ordering site (https://citychickennhas.de/bestellen/en/koeln) is a Next.js app that
talks to a small JSON API under /bestellen/api. This script uses the same endpoints:

    GET  /me                                    -> who is logged in
    GET  /store/<slug>?locale=en                -> store info (we need its "id")
    GET  /slots?store=<id>&date=YYYY-MM-DD&party=N&locale=en
                                                -> {date, today, bookableDates, rules, slots:[...]}
    POST /holds {store, scheduledAt, partySize} -> reserves the slot for ~10 minutes
    GET  /holds                                 -> your current hold (or null)

Re-posting a hold for the same slot renews it, which is what the site's own
"extend" button does. Push notifications go through ntfy (https://ntfy.sh).

Authentication is your browser session cookie (see README.md). The site's login
token lasts an hour and the server renews it via Set-Cookie, so we keep those
updates and write them back to the cookie file. Only the Python standard library
is used, so there is nothing to install.
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
from email.utils import parsedate_to_datetime
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE = "https://citychickennhas.de"
API = f"{BASE}/bestellen/api"
TZ = ZoneInfo("Europe/Berlin")
EXTEND_BELOW_S = 90  # renew a hold once less than this is left
HOLD_CHECK_S = 20
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
    def __init__(self, cookie: str, locale: str, save_to: str | None = None, timeout: float = 20):
        self.jar = dict(
            part.strip().split("=", 1) for part in cookie.split(";") if "=" in part
        )
        self.locale = locale
        self.save_to = save_to
        self.timeout = timeout

    @property
    def cookie(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.jar.items())

    def _absorb(self, headers) -> None:
        """Apply Set-Cookie headers (the renewed login) and persist them."""
        changed = False
        for header in headers.get_all("Set-Cookie") or []:
            first, *rest = header.split(";")
            if "=" not in first:
                continue
            name, value = (x.strip() for x in first.split("=", 1))
            attrs = {a.split("=", 1)[0].strip().lower(): a.split("=", 1)[-1].strip() for a in rest}
            expired = False
            if "max-age" in attrs:
                try:
                    expired = int(attrs["max-age"]) <= 0
                except ValueError:
                    pass
            elif "expires" in attrs:
                try:
                    expired = parsedate_to_datetime(attrs["expires"]) < datetime.now(timezone.utc)
                except (TypeError, ValueError):
                    pass
            if expired or not value:
                changed |= self.jar.pop(name, None) is not None
            elif self.jar.get(name) != value:
                self.jar[name] = value
                changed = True
        if changed and self.save_to:
            tmp = f"{self.save_to}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(self.cookie + "\n")
            os.replace(tmp, self.save_to)

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
                self._absorb(resp.headers)
                raw = resp.read()
                # every response is wrapped as {"data": ...}
                return (json.loads(raw) or {}).get("data") if raw else None
        except urllib.error.HTTPError as e:
            self._absorb(e.headers)
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


class Notifier:
    """Sends phone push notifications via ntfy. A no-op when no topic is set."""

    def __init__(self, server: str, topic: str | None):
        self.url = f"{server.rstrip('/')}/{topic}" if topic else None

    def send(self, title: str, message: str, click: str | None = None, urgent: bool = False) -> bool:
        if not self.url:
            return False
        # ntfy reads these as HTTP headers, so they must stay ASCII
        headers = {"Title": title.encode("ascii", "replace").decode(), "Tags": "poultry_leg"}
        if click:
            headers["Click"] = click
        if urgent:
            headers["Priority"] = "urgent"
        req = urllib.request.Request(self.url, data=message.encode(), headers=headers, method="POST")
        try:
            urllib.request.urlopen(req, timeout=10).close()
            return True
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log(f"Could not send push notification: {e}")
            return False


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


def seconds_left(hold: dict) -> float:
    """Time left on a hold, measured on the server's clock so a skewed local clock doesn't matter."""
    now = parse_ts(hold["serverNow"]) if hold.get("serverNow") else datetime.now(TZ)
    return (parse_ts(hold["expiresAt"]) - now).total_seconds()


def keep_held(client: Client, hold: dict, minutes: float, notify: Notifier, page: str) -> int:
    """Renew the hold until you start paying, give it up, or `minutes` have passed."""
    start = hold["slot"]["start"]
    deadline = time.monotonic() + minutes * 60
    log(f"Keeping the slot held for up to {minutes:g} min. Ctrl+C to stop (the hold then just runs out).")
    while True:
        try:
            cur = client.current_hold()
        except ApiError as e:
            if e.status == 401:
                notify.send("Bot logged out", "Cookie expired, can't extend. Finish the order now!", click=page, urgent=True)
                log("Session expired, can't extend anymore.")
                return 1
            log(f"Could not check the hold: {e}")
            cur = hold
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            log(f"Network error while checking the hold: {e}")
            cur = hold

        if not cur:
            log("Hold is gone (order placed, released, or expired). Done.")
            return 0
        if cur.get("orderNumber") is not None:
            log("You're in checkout. The site keeps the slot while you pay, so I stop extending.")
            return 0
        if cur["slot"]["start"] != start:
            log("You picked a different slot in the browser. Stopping.")
            return 0

        left = seconds_left(cur)
        if left < EXTEND_BELOW_S:
            if time.monotonic() > deadline:
                notify.send("Slot hold running out", f"Stopped extending after {minutes:g} min. "
                            f"About {max(left, 0):.0f}s left.", click=page, urgent=True)
                log("Max keep time reached, letting the hold run out.")
                return 0
            try:
                cur = client.hold(cur["storeId"], start, cur["partySize"])
                log(f"Extended, now held until {parse_ts(cur['expiresAt']):%H:%M:%S}.")
            except (ApiError, urllib.error.URLError, TimeoutError, ConnectionError) as e:
                notify.send("Could not extend your slot", f"{e}. Finish the order now!", click=page, urgent=True)
                log(f"Extending failed: {e}")
        hold = cur
        time.sleep(min(HOLD_CHECK_S, max(left - EXTEND_BELOW_S + 5, 5)))


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
    p.add_argument("--ntfy-topic", default=os.environ.get("NHAS_NTFY_TOPIC"),
                   help="ntfy topic for phone push (default: $NHAS_NTFY_TOPIC). Pick something unguessable")
    p.add_argument("--ntfy-server", default="https://ntfy.sh")
    p.add_argument("--keep-held", type=float, default=30, metavar="MINUTES",
                   help="Keep renewing the hold for up to this long until you check out (default: 30, 0 = off)")
    p.add_argument("--test-push", action="store_true", help="Send a test push notification and exit")
    return p.parse_args(argv)


def load_cookie(args: argparse.Namespace) -> tuple[str, str | None]:
    """Return the cookie and the file to save renewed logins to (None if not from a file)."""
    cookie = args.cookie or os.environ.get("NHAS_COOKIE")
    if cookie:
        return cookie.removeprefix("Cookie:").strip(), None
    if os.path.exists(args.cookie_file):
        with open(args.cookie_file, encoding="utf-8") as fh:
            cookie = fh.read().strip()
    if not cookie:
        sys.exit("No cookie found. Put your browser's Cookie header in cookie.txt (see README.md).")
    return cookie.removeprefix("Cookie:").strip(), args.cookie_file


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    notify = Notifier(args.ntfy_server, args.ntfy_topic)
    page = f"{BASE}/bestellen/{args.locale}/{args.store}"
    if args.test_push:
        if not args.ntfy_topic:
            sys.exit("Set --ntfy-topic or $NHAS_NTFY_TOPIC first.")
        if not notify.send("Nhas bot test", "Push works. Tap to open the order page.", click=page):
            return 1
        log("Test push sent.")
        return 0
    cookie, cookie_file = load_cookie(args)
    if cookie_file is None:
        log("Note: cookie given via --cookie/$NHAS_COOKIE, so renewed logins are not saved. Use cookie.txt for long runs.")
    client = Client(cookie, args.locale, save_to=cookie_file)
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
                msg = f"{parse_ts(slot['start']):%a %d.%m %H:%M} ({slot['remainingPersons']} places left)"
                log(f"Free: {msg}. Dry run, not reserving.")
                notify.send("Free slot found", msg, click=page)
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
                    what = f"{start:%a %d.%m %H:%M} for {args.party}"
                    log(f"RESERVED {what}{until}.")
                    log(f"Finish your order in the browser now: {page}")
                    keep = f" I keep it held for up to {args.keep_held:g} min." if args.keep_held > 0 else ""
                    notify.send("Slot reserved!", f"{what}{until}.{keep} Tap to order and pay.",
                                click=page, urgent=True)
                    if args.keep_held > 0 and expires:
                        return keep_held(client, hold, args.keep_held, notify, page)
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
