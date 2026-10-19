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

## How it works

The site's frontend calls a JSON API under `/bestellen/api`. The bot uses the same calls:
`GET /me` (login check), `GET /store/koeln` (store id), `GET /slots` (availability) and
`POST /holds` (reserve, and again to extend), `GET /holds` (watch the hold). A slot counts as free when it is `bookable`, has
`remainingPersons >= party`, and starts after the store's minimum lead time, which is the
same rule the site uses.

If you get "Not logged in", your cookie expired: copy a fresh one.
