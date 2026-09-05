"""Read KEY=value lines from .env into os.environ.

Its own module so that anything needing a webhook or a token does not have to
import the exchange client to get it. paper.py and control.py must be able to
prove they never load that client; a shared helper living inside it made the
proof false.
"""
import os

ENV_FILE = os.environ.get("CRYPTOBRO_ENV", ".env")


def load_env(path=ENV_FILE):
    """Already-set variables win, so an explicit `export` or a systemd
    EnvironmentFile still overrides the file."""
    try:
        with open(path) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
