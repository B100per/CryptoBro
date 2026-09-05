"""Discord alerts for a bot nobody is watching.

    python3 notify.py "message"    # send one, to check the webhook works

Never raises: a broken webhook must not take the trading loop down with it.
"""
import json
import os
import sys
import urllib.error
import urllib.request

from binance_client import load_env

UA = "CryptoBro (https://github.com/B100per/CryptoBro, 0.1)"
COLORS = {"info": 3447003, "good": 3066993, "warn": 16776960, "bad": 15158332}


def send(title, message, level="info"):
    """Post to Discord. Returns True if it landed, False otherwise."""
    load_env()
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return False
    payload = {"embeds": [{"title": title[:256],
                           "description": message[:4000],
                           "color": COLORS.get(level, COLORS["info"])}]}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        # Cloudflare blocks urllib's default User-Agent outright (403, code 1010),
        # so Discord never sees the request. Sending one is not optional.
        headers={"Content-Type": "application/json", "User-Agent": UA},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except Exception as e:
        # ponytail: alerting is best-effort by definition. If Discord is down,
        # that is not a reason to stop trading or to crash the loop.
        print(f"notify failed: {e}", file=sys.stderr)
        return False


def orders(rows, quote, live):
    """Format a trade plan as one alert."""
    if not rows:
        return
    lines = [f"{side} {pair} {qty:.8f} = {value:.2f} {quote}"
             for side, pair, qty, value in rows]
    send(f"{'EXECUTED' if live else 'DRY RUN'}: {len(rows)} orders",
         "```\n" + "\n".join(lines) + "\n```", "good" if live else "info")


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "CryptoBro is alive."
    print("sent" if send("CryptoBro", msg) else
          "not sent (DISCORD_WEBHOOK_URL missing or the post failed)")
