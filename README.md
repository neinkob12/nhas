# nhas

Small bot that watches the Nhas City Chicken dine-in slots
(https://citychickennhas.de/bestellen/en/koeln) and reserves one the moment it is free.

"Reserve" means the same thing as clicking a slot on the site: the slot is **held for
about 10 minutes**. You still need to pick your food and pay in the browser to actually
book it. Because the bot uses your browser's login cookie, the hold shows up in your
browser right away.

## Setup

Needs Python 3.10+. No packages to install.

1. Log in at https://citychickennhas.de/bestellen/en/koeln in your browser.
2. Open DevTools (F12), go to the **Network** tab and reload the page.
3. Click any request to `citychickennhas.de/bestellen/api/...`, find **Request Headers**,
   and copy the whole value of the `Cookie` header.
4. Paste it into a file called `cookie.txt` next to the script (it is gitignored).
   Never commit or share it: it is your login.

## Usage

```bash
# Just look, don't reserve
python3 nhas_slot_bot.py --party 2 --once --dry-run

# Keep checking every 30s and grab the first free slot for 2 people tomorrow between 18:00 and 20:30
python3 nhas_slot_bot.py --party 2 --date 2026-10-20 --earliest 18:00 --latest 20:30

# Any day in the next 3 days
python3 nhas_slot_bot.py --party 4 --days-ahead 3
```

When it reserves a slot it prints `RESERVED ...` and exits. Then finish your order in the browser
within the 10 minutes.

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

## How it works

The site's frontend calls a JSON API under `/bestellen/api`. The bot uses the same calls:
`GET /me` (login check), `GET /store/koeln` (store id), `GET /slots` (availability) and
`POST /holds` (reserve). A slot counts as free when it is `bookable`, has
`remainingPersons >= party`, and starts after the store's minimum lead time, which is the
same rule the site uses.

If you get "Not logged in", your cookie expired: copy a fresh one.
