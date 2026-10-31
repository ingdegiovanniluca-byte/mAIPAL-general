"""Who may come into mAIPAL as the administrator of an organization - until subscriptions are
live, a local file stands for them: each address listed is someone who "subscribed" for their
organization (they become its administrator, with the plan's limits). Everyone else comes in
only when an administrator added them to their organization (see server.py, tenants).

The file (ORG_ADMINS_FILE, default backend/data/access/org_admins.txt), one administrator per line:

    mario@impresa.it ; Impresa Rossi ; max_users=5 ; max_collaborators=5 ; max_admins=1

Only the e-mail is needed; the organization's name and the limits are optional (the defaults
below). Lines starting with # are comments. The file is read again when it changes - no restart.
Kept free of server imports so it can be tested on its own.
"""
import os
from pathlib import Path
from typing import Optional

DEFAULT_PLAN = {"max_users": 5, "max_collaborators": 5, "max_admins": 1}
PLAN_KEYS = tuple(DEFAULT_PLAN)
_DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "access" / "org_admins.txt"
_cache = {"key": None, "admins": {}}


def path() -> Path:
    return Path(os.environ.get("ORG_ADMINS_FILE") or _DEFAULT_PATH)


def parse(text: str) -> dict:
    """{email: {"org": name, "plan": {max_users, max_collaborators, max_admins}}}"""
    out = {}
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(";")]
        email = parts[0].lower()
        if "@" not in email or " " in email:
            continue
        org, plan = "", dict(DEFAULT_PLAN)
        for p in parts[1:]:
            if "=" in p:
                k, v = (x.strip() for x in p.split("=", 1))
                if k in PLAN_KEYS and v.isdigit():
                    plan[k] = int(v)
            elif p and not org:
                org = p[:120]
        out[email] = {"org": org, "plan": plan}
    return out


def admins(fallback_email: Optional[str] = None) -> dict:
    """The administrators listed (read again when the file changes). Without a file yet, the
    fallback address alone (the installation's first administrator), so nobody is locked out."""
    p = path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return {fallback_email.lower(): {"org": "", "plan": dict(DEFAULT_PLAN)}} if fallback_email else {}
    if _cache["key"] != key:
        _cache.update(key=key, admins=parse(p.read_text(encoding="utf-8")))
    return _cache["admins"]


def entry(email: str, fallback_email: Optional[str] = None) -> Optional[dict]:
    return admins(fallback_email).get((email or "").strip().lower())
