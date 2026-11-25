"""QR labels of an organization (for tools, sites, info points): what the label holds and how it is drawn.

The label holds only a link with a random code (APP_BASE_URL/q/<code>); what it shows lives in the app, so the
administrator changes it without printing the label again, and only who is in the organization can open it.
The code: 12 characters out of 31 (no 0/O, 1/I/L), about 59 bits - not guessable; printed in groups of 4
(K7P3-XQ9M-2TRA) to be typed when the label is worn."""
import os
import re
import secrets
from typing import List, Optional

import segno

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 12
KINDS = {"attrezzo": "Attrezzo", "cantiere": "Cantiere", "punto": "Punto informativo", "altro": "Altro"}
VISIBILITY = {"public": "Pubblico: chiunque lo scansioni", "org": "Tutta l'organizzazione", "admins": "Solo amministratori"}
MAX_TITLE, MAX_TEXT, MAX_LINKS, MAX_LINK_LABEL, MAX_URL = 120, 5000, 10, 80, 1000


def new_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


def norm_code(raw: str) -> str:
    """What was scanned or typed -> the code: 'k7p3-xq9m 2tra', or the whole link, -> 'K7P3XQ9M2TRA'."""
    s = (raw or "").strip()
    if "/q/" in s:
        s = s.rsplit("/q/", 1)[1]
    s = s.split("?", 1)[0].split("#", 1)[0]
    s = re.sub(r"[\s\-./]", "", s).upper()
    return s if len(s) == CODE_LEN and all(c in ALPHABET for c in s) else ""


def code_label(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def link(code: str) -> str:
    return f"{(os.environ.get('APP_BASE_URL') or '').rstrip('/')}/q/{code}"


def images(code: str) -> dict:
    """The label's QR: SVG (sharp at any size, for printing) and PNG (to share / download). Error correction Q:
    still readable with a quarter of it scratched or dirty."""
    q = segno.make(link(code), error="q", micro=False)
    return {"svg": q.svg_data_uri(scale=10, border=2, dark="#111111"), "png": q.png_data_uri(scale=12, border=2, dark="#111111")}


def clean_links(links) -> List[dict]:
    """Links shown on the label's page: only http(s) (never javascript: or others), with a label."""
    out = []
    for x in (links or [])[:MAX_LINKS]:
        if not isinstance(x, dict):
            continue
        url = str(x.get("url") or "").strip()[:MAX_URL]
        if not url:
            continue
        if not re.match(r"^https?://", url, re.I):
            if re.match(r"^[\w-]+(\.[\w-]+)+(/|$)", url):   # "drive.google.com/..." -> https://
                url = "https://" + url
            else:
                raise ValueError(f"Il link «{url[:40]}» non è un indirizzo web (deve iniziare con https://)")
        label = str(x.get("label") or "").strip()[:MAX_LINK_LABEL] or re.sub(r"^https?://(www\.)?", "", url, flags=re.I).split("/")[0]
        out.append({"label": label, "url": url})
    return out


def clean_text(text: Optional[str]) -> str:
    return (text or "").replace("\r\n", "\n").strip()[:MAX_TEXT]
