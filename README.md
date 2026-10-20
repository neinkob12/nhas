# nhas

Small bot that watches the Nhas City Chicken dine-in slots
(https://citychickennhas.de/bestellen/en/koeln) and reserves one the moment it is free.

"Reserve" means the same thing as clicking a slot on the site: the slot is **held for
about 10 minutes**. You still need to pick your food and pay in the browser to actually
book it. Because the bot uses your browser's login cookie, the hold shows up in your
browser right away.

## Setup

Needs Python 3.10+. No packages to install.

The bot needs **its own login**. The site's login token lasts one hour and renews itself; if your
normal browser and the bot share one login, both try to renew it and the site can log you out.

1. Open a **private/incognito window** and log in at https://citychickennhas.de/bestellen/en/koeln.
2. Open DevTools (F12), go to the **Network** tab and reload the page.
3. Click the `me` request (or any `.../bestellen/api/...` one), find **Request Headers**, and
   copy the whole value of the `cookie` header (from `bp-auth-token.0=` to the end).
4. Paste it into a file called `cookie.txt` next to the script (it is gitignored).
5. **Close the private window without logging out.** Logging out would end the bot's login too.

Never commit or share `cookie.txt`: it is your login. The bot rewrites it whenever the site renews
the login, so a long run stays logged in. If you log out anywhere on the site later, the bot's
login may end too; then repeat these steps.

## Usage

```bash
# Just look, don't reserve
python3 nhas_slot_bot.py --party 2 --once --dry-run

# Keep checking every 30s and grab the first free slot for 2 people tomorrow between 18:00 and 20:30
python3 nhas_slot_bot.py --party 2 --date 2026-10-20 --earliest 18:00 --latest 20:30

# Any day in the next 3 days
python3 nhas_slot_bot.py --party 4 --days-ahead 3
```

When it reserves a slot it prints `RESERVED ...`, sends a push to your phone (if set up) and then
keeps the hold alive for you (see below).

## Phone push notifications (ntfy)

1. Install the free **ntfy** app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy),
   [iPhone](https://apps.apple.com/app/ntfy/id1625396347)). No account needed.
2. In the app, tap **+** and subscribe to a topic. Anyone who knows the name can read it, so
   make it unguessable, e.g. `nhas-jakob-7f3k9q`.
3. Tell the bot the same topic and send a test:

   ```bash
   export NHAS_NTFY_TOPIC=nhas-jakob-7f3k9q
   python3 nhas_slot_bot.py --test-push
   ```

You get an urgent push when a slot is reserved. **Tapping it opens the order page on your phone.**
The hold belongs to your account, not the computer, so as long as you are logged in to the same
account in your phone's browser you'll see the held slot and can order and pay right there.

## Auto-extend

A hold only lasts 10 minutes. After reserving, the bot stays running and renews the hold whenever
less than 90 seconds are left (the same thing the site's "extend" button does), so you have time
to get to your phone. It stops when:

- you start checkout (the site keeps the slot while you pay),
- you release the slot or pick another one in the browser,
- `--keep-held` minutes have passed (default 30, `--keep-held 0` turns it off). You get a push
  when it gives up.

| Option | Default | Meaning |
| --- | --- | --- |
| `--party` | 2 | Number of people |
| `--date` | any bookable | Only this date, repeatable |
| `--days-ahead` | 7 | Range to search when no `--date` is given |
| `--earliest` / `--latest` | none | Time window for the slot start |
| `--interval` | 30 | Seconds between checks (please don't go much lower) |
| `--once` | off | Check once instead of looping |
| `--dry-run` | off | Never reserve, only report |
| `--store` | koeln | Store slug from the URL |
| `--cookie` | `$NHAS_COOKIE` or `cookie.txt` | Cookie header value |
| `--ntfy-topic` | `$NHAS_NTFY_TOPIC` | ntfy topic for phone pushes |
| `--keep-held` | 30 | Minutes to keep renewing the hold, 0 = off |
| `--test-push` | off | Send a test push and exit |
| `--keep-going` | off | Keep looking after a slot you didn't take, skipping it from then on |
| `--declined-file` | declined.txt | Where skipped slots are remembered |

## How it works

The site's frontend calls a JSON API under `/bestellen/api`. The bot uses the same calls:
`GET /me` (login check), `GET /store/koeln` (store id), `GET /slots` (availability) and
`POST /holds` (reserve, and again to extend), `GET /holds` (watch the hold). A slot counts as free when it is `bookable`, has
`remainingPersons >= party`, and starts after the store's minimum lead time, which is the
same rule the site uses.

If you get "Not logged in", your cookie expired: copy a fresh one.

## Keep going after a reservation

With `--keep-going` the bot doesn't stop after holding a slot. It watches what you do with it:

- **You pay** → it sends "Booked!" and stops.
- **You release it, cancel the order, or let it run out** → it remembers that slot in
  `declined.txt`, never grabs it again, and keeps looking for another one.
- **You pick a different slot yourself** → it stops, so it never fights you.

It also never replaces a slot you're already holding: if something matching frees up while you
hold one, it only sends a push. Delete `declined.txt` to make it consider old slots again.

```bash
caffeinate -i python3 nhas_slot_bot.py --party 2 --keep-going --ntfy-topic YOUR-TOPIC
```

## New bookable days

Nhas doesn't publish when a new day opens for booking. The bot watches for it: when a date
shows up that wasn't bookable before, it prints `NEW DAY OPENED: <date>` with the time and
sends a push. Once that time is known, put it in `NEW_DAYS_INFO` at the top of `web/app.js`
so the website shows it.

## Website

`web/` is a static setup guide that walks someone through installing and running the bot on
their own computer, step by step, with commands filled in for Mac or Windows. It serves the
bot file itself, so the GitHub repo can stay private.

Deploy on Vercel: import this repo, keep the defaults. `vercel.json` copies `web/` and
`nhas_slot_bot.py` into `public/` at build time, so the script on the site always matches
the one in the repo. The Geist fonts in `web/fonts/` are served from the site itself (SIL Open Font
License). Preview locally with:

```bash
rm -rf public && cp -r web public && cp nhas_slot_bot.py public/ && python3 -m http.server -d public
```
