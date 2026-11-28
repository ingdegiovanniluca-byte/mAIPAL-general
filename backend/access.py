"""Who may come into mAIPAL as the administrator of an organization - until subscriptions are
live, a local file stands for them: each address listed is someone who "subscribed" for their
organization (they become its administrator, with the plan's limits). Everyone else comes in
only when an administrator added them to their organization (see server.py, tenants).

The file (ORG_ADMINS_FILE, default backend/data/access/org_admins.txt), one administrator per line:

    mario@impresa.it ; Impresa Rossi ; max_users=5 ; max_collaborators=5 ; max_admins=1 ; verticali=artigiano

Only the e-mail is needed; the organization's name, the limits and the verticals are optional (the
defaults below). verticali= lists the vertical packs the organization may use (artigiano, fitness,
veterinario; several with commas; "tutti" or no verticali= = all of them, "nessuno" = only the general
app): one only -> it is the organization's vertical, set by itself (later it will come from the
subscription). Lines starting with # are comments. The file is read again when it changes - no restart.
Kept free of server imports so it can be tested on its own.
"""
import os
import re
from pathlib import Path
from typing import Optional

import verticals as vx

DEFAULT_PLAN = {"max_users": 5, "max_collaborators": 5, "max_admins": 1}
PLAN_KEYS = tuple(DEFAULT_PLAN)
VERTICAL_KEYS = tuple(vx.PACKS)
_VERTICAL_ALIASES = {"artigiani": "artigiano", "veterinari": "veterinario", "vet": "veterinario", "palestra": "fitness",
                     "palestre": "fitness"}


def parse_verticals(value: str) -> Optional[list]:
    """'artigiano, fitness' -> ['artigiano', 'fitness']; 'tutti' -> None (all); 'nessuno' -> [] (none).
    Unknown names are left out."""
    v = (value or "").strip().lower()
    if v in ("", "tutti", "tutto", "all"):
        return None
    if v in ("nessuno", "nessun", "none", "-"):
        return []
    out = []
    for name in re.split(r"[,|+/\s]+", v):
        name = _VERTICAL_ALIASES.get(name, name)
        if name in VERTICAL_KEYS and name not in out:
            out.append(name)
    return out
_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "access" / "org_admins.txt"
_cache = {"key": None, "admins": {}}


def path() -> Path:
    return Path(os.environ.get("ORG_ADMINS_FILE") or _DEFAULT_PATH)


def parse(text: str) -> dict:
    """{email: {"org": name, "plan": {max_users, max_collaborators, max_admins}, "verticals": [..] | None (all)}}"""
    out = {}
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        email = parts[0].lower()
        if "@" not in email or " " in email:
            continue
        org, plan, verts = "", dict(DEFAULT_PLAN), None
        for p in parts[1:]:
            if "=" in p:
                k, v = (x.strip() for x in p.split("=", 1))
                k = k.lower()
                if k in PLAN_KEYS and v.isdigit():
                    plan[k] = int(v)
                elif k in ("verticali", "verticale", "verticals"):
                    verts = parse_verticals(v)
            elif p and not org:
                org = p[:120]
        out[email] = {"org": org, "plan": plan, "verticals": verts}
    return out


def admins(fallback_email: Optional[str] = None) -> dict:
    """The administrators listed (read again when the file changes). Without a file yet, the
    fallback address alone (the installation's first administrator), so nobody is locked out."""
    p = path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return {fallback_email.lower(): {"org": "", "plan": dict(DEFAULT_PLAN), "verticals": None}} if fallback_email else {}
    if _cache["key"] != key:
        _cache.update(key=key, admins=parse(p.read_text(encoding="utf-8")))
    return _cache["admins"]


def entry(email: str, fallback_email: Optional[str] = None) -> Optional[dict]:
    return admins(fallback_email).get((email or "").strip().lower())
