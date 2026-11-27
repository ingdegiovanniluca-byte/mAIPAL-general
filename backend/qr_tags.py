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


STYLES = {"maipal": "mAIPAL (forma e colori del logo)", "classic": "Classico (bianco e nero)"}
EC = {"maipal": "h", "classic": "q"}   # mAIPAL: the logo covers the middle -> the highest error correction (30%)
BORDER = 2                            # white margin, in modules (the AR counts on it: printed side = modules + 4)

# the logo's colors (dark enough to be read as the QR's dark modules: contrast on white 4.7, 6.4, 3.9)
TEAL, MAGENTA, PINK = "#007E9A", "#B9006C", "#FF0061"
# the 3 big squares' rounding (modules, of 7): the logo's drop, with sides straight enough (from 19% to 81%) for the
# augmented reality to find their lines precisely (see the app's lib/arPose.js refineQuad)
FINDER_R = 1.3
_LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "maipal-logo.png")


def _qr(code: str, style: str):
    return segno.make(link(code), error=EC.get(style, "q"), micro=False)


def images(code: str, style: str = "classic") -> dict:
    """The label's QR: SVG (sharp at any size, for printing) and PNG (to share / download).
    classic: black squares, error correction Q (readable with a quarter of it scratched or dirty).
    maipal: the logo's drop shape (three round corners, one sharp) and colors, the logo in the middle."""
    if style == "maipal":
        return _maipal_images(code)
    q = _qr(code, "classic")
    return {"svg": q.svg_data_uri(scale=10, border=BORDER, dark="#111111"), "png": q.png_data_uri(scale=12, border=BORDER, dark="#111111")}


def modules(code: str, style: str = "classic") -> int:
    """How many modules (squares) a side of the QR has, without its white margin: with the printed size, the size of
    the QR itself, for the augmented reality."""
    return _qr(code, style).symbol_size(border=0)[0]


# ---------------------------------------------------------------- the mAIPAL style
def _layout(code: str):
    """The dark modules to draw as drops (the 3 finder squares and the logo's place left out), the matrix size, the
    logo's box (in modules)."""
    q = _qr(code, "maipal")
    m = [list(r) for r in q.matrix]
    n = len(m)
    logo = max(7, int(round(n * 0.26)) | 1)            # odd, about a quarter of the side: ~7% of the modules
    lo = (n - logo) // 2
    finder = lambda r, c: (r < 7 and c < 7) or (r < 7 and c >= n - 7) or (r >= n - 7 and c < 7)
    in_logo = lambda r, c: lo <= r < lo + logo and lo <= c < lo + logo
    cells = [(r, c) for r in range(n) for c in range(n) if m[r][c] & 1 and not finder(r, c) and not in_logo(r, c)]
    return n, cells, (lo, logo)


def _drop_path(x: float, y: float, s: float, r: float) -> str:
    """The logo's drop: a square of side s with its top-left corner sharp and the other three rounded (radius r)."""
    return (f"M{x:.2f} {y:.2f}H{x + s - r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x + s:.2f} {y + r:.2f}V{y + s - r:.2f}"
            f"A{r:.2f} {r:.2f} 0 0 1 {x + s - r:.2f} {y + s:.2f}H{x + r:.2f}A{r:.2f} {r:.2f} 0 0 1 {x:.2f} {y + s - r:.2f}Z")


def _maipal_svg(code: str) -> str:
    import base64
    n, cells, (lo, logo) = _layout(code)
    u = 10                                              # units per module
    size = (n + 2 * BORDER) * u
    off = BORDER * u
    mods = "".join(_drop_path(off + c * u, off + r * u, u, 0.36 * u) for r, c in cells)
    finders = ""
    for (fr, fc), eye in (((0, 0), MAGENTA), ((0, n - 7), MAGENTA), ((n - 7, 0), PINK)):
        x, y = off + fc * u, off + fr * u
        finders += (f'<path d="{_drop_path(x, y, 7 * u, FINDER_R * u)}" fill="{TEAL}"/>'
                    f'<path d="{_drop_path(x + u, y + u, 5 * u, (FINDER_R - 0.6) * u)}" fill="#fff"/>'
                    f'<path d="{_drop_path(x + 2 * u, y + 2 * u, 3 * u, 1.0 * u)}" fill="{eye}"/>')
    lx = off + lo * u
    pad = 0.5 * u
    with open(_LOGO, "rb") as fh:
        logo_uri = "data:image/png;base64," + base64.b64encode(fh.read()).decode()
    badge = (f'<path d="{_drop_path(lx + pad, lx + pad, logo * u - 2 * pad, 1.6 * u)}" fill="#fff"/>'
             f'<image href="{logo_uri}" x="{lx + 1.5 * u:.1f}" y="{lx + 1.1 * u:.1f}" width="{logo * u - 3 * u:.1f}" '
             f'height="{logo * u - 2.2 * u:.1f}" preserveAspectRatio="xMidYMid meet"/>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{MAGENTA}"/>'
            f'<stop offset="0.5" stop-color="{PINK}"/><stop offset="1" stop-color="{TEAL}"/></linearGradient></defs>'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{mods}" fill="url(#g)"/>{finders}{badge}</svg>')


def _maipal_png(code: str, px: int = 14) -> bytes:
    """The same drawn as an image (px per module), smoothed (drawn 3x larger, then reduced)."""
    import io
    from PIL import Image, ImageDraw
    n, cells, (lo, logo) = _layout(code)
    k = 3
    u = px * k
    size = (n + 2 * BORDER) * u
    off = BORDER * u
    hexrgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
    drop = lambda d, x, y, s, r, fill: d.rounded_rectangle([x, y, x + s - 1, y + s - 1], radius=r, fill=fill,
                                                           corners=(False, True, True, True))
    mask = Image.new("L", (size, size), 0)
    dm = ImageDraw.Draw(mask)
    for r, c in cells:
        drop(dm, off + c * u, off + r * u, u, int(0.36 * u), 255)
    # the diagonal gradient magenta -> pink -> teal, through the modules' mask
    import numpy as np
    t = (np.add.outer(np.arange(size), np.arange(size)) / (2 * size - 2))[..., None]
    a, b, c3 = (np.array(hexrgb(x), dtype=np.float32) for x in (MAGENTA, PINK, TEAL))
    grad = np.where(t < 0.5, a + (b - a) * (t / 0.5), b + (c3 - b) * ((t - 0.5) / 0.5)).astype(np.uint8)
    img = Image.new("RGB", (size, size), "white")
    img.paste(Image.fromarray(grad, "RGB"), (0, 0), mask)
    d = ImageDraw.Draw(img)
    for (fr, fc), eye in (((0, 0), MAGENTA), ((0, n - 7), MAGENTA), ((n - 7, 0), PINK)):
        x, y = off + fc * u, off + fr * u
        drop(d, x, y, 7 * u, int(FINDER_R * u), hexrgb(TEAL))
        drop(d, x + u, y + u, 5 * u, int((FINDER_R - 0.6) * u), (255, 255, 255))
        drop(d, x + 2 * u, y + 2 * u, 3 * u, int(1.0 * u), hexrgb(eye))
    lx = off + lo * u
    pad = u // 2
    drop(d, lx + pad, lx + pad, logo * u - 2 * pad, int(1.6 * u), (255, 255, 255))
    lg = Image.open(_LOGO).convert("RGBA")
    bw, bh = logo * u - 3 * u, logo * u - int(2.2 * u)
    sc = min(bw / lg.width, bh / lg.height)
    lg = lg.resize((max(1, int(lg.width * sc)), max(1, int(lg.height * sc))), Image.LANCZOS)
    img.paste(lg, (lx + int(1.5 * u) + (bw - lg.width) // 2, lx + int(1.1 * u) + (bh - lg.height) // 2), lg)
    img = img.resize((size // k, size // k), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _maipal_images(code: str) -> dict:
    import base64
    svg = _maipal_svg(code)
    return {"svg": "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode(),
            "png": "data:image/png;base64," + base64.b64encode(_maipal_png(code)).decode()}


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
