import notify

sent = []
notify.urllib.request.urlopen = lambda req, timeout=None: sent.append(
    (req.full_url, __import__("json").loads(req.data))) or __import__(
    "contextlib").nullcontext()

import os
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
assert notify.send("t", "body", "bad") is True
url, payload = sent[-1]
assert payload["embeds"][0]["color"] == notify.COLORS["bad"]
assert payload["embeds"][0]["description"] == "body"

# oversized content is truncated rather than rejected by Discord
notify.send("x" * 500, "y" * 9000)
_, payload = sent[-1]
assert len(payload["embeds"][0]["title"]) == 256
assert len(payload["embeds"][0]["description"]) == 4000

# no webhook configured is a quiet no-op, not a crash
os.environ["DISCORD_WEBHOOK_URL"] = ""
before = len(sent)
assert notify.send("t", "b") is False and len(sent) == before

# a failing webhook must not raise into the trading loop
def boom(req, timeout=None):
    raise OSError("network down")
notify.urllib.request.urlopen = boom
os.environ["DISCORD_WEBHOOK_URL"] = "https://example.invalid/hook"
assert notify.send("t", "b") is False
print("ok")
