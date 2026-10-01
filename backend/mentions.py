"""@agenti nella chat: "...informazioni sul paziente... @task richiamare la padrona giovedì".

The text before the first tag goes to the action selected in the chat (the main agent);
each tag's piece - up to the next tag - goes to that agent, which also receives the whole
message as context. Spoken forms work too, since "@" can't be dictated: "agente task ...",
"chiocciola task ..." (how speech-to-text writes "@"). An e-mail address such as
mario@gmail.com is never a tag: "@" must start a word and be followed by an agent name.

The same rules are mirrored in frontend/src/lib/mentions.js (menu, chips, highlighting).
"""
import re
import unicodedata

# agent key -> names accepted after "@" (first = the one shown in the menu)
AGENTS = {
    "task_todo": ["task", "todo", "to-do", "promemoria"],
    "info_upload": ["nota", "salva", "info"],
    "info_request": ["cerca", "chiedi"],
    "journal": ["diario"],
    "list_update": ["lista", "liste"],
    "scheduled_action": ["azione", "azioni"],
}
ALIASES = {alias: key for key, names in AGENTS.items() for alias in names}
_NAMES = "|".join(sorted((re.escape(a) for a in ALIASES), key=len, reverse=True))
# "@task", or dictated "agente task" / "chiocciola task" (optionally followed by ":" or ",")
_TAG_RE = re.compile(
    rf"(?:(?<=^)|(?<=[\s(\[,;.!?]))(?:@\s?|(?:agente|chiocciola)\s+)({_NAMES})(?![\w-])\s*[:,]?",
    re.IGNORECASE,
)


def split_mentions(text: str) -> tuple[str, list[dict]]:
    """-> (main text, [{"agent": key, "tag": alias, "text": piece}, ...]) in message order.
    Pieces left empty ("@task" with nothing after it) are dropped."""
    text = text or ""
    matches = list(_TAG_RE.finditer(text))
    if not matches:
        return text.strip(), []
    main = text[:matches[0].start()].strip()
    parts = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        piece = text[m.end():end].strip().strip(",;").strip()
        alias = m.group(1).lower()
        if piece:
            parts.append({"agent": ALIASES[alias], "tag": alias, "text": piece})
    return main, parts


# ======================= persone e gruppi del team =======================
# "@mario.rossi" shares the saved information with that team member, "@team" with the whole
# team; the same slugs are built by frontend/src/lib/mentions.js for the "@" menu.
GROUP_TAGS = {"team", "tutti"}


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFD", name or "")
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn").lower()
    s = re.sub(r"[^a-z0-9]+", ".", s).strip(".")
    return s or "utente"


def people_directory(members: list[dict]) -> dict:
    """{slug: member} for the team members, in a stable order (by user_id); a repeated name
    gets the last 4 characters of the user id ("mario.rossi-1a2b")."""
    out = {}
    for m in sorted(members, key=lambda x: x.get("user_id") or ""):
        slug = slugify(m.get("name") or (m.get("email") or "").split("@")[0])
        if slug in out or slug in GROUP_TAGS or slug in ALIASES:
            slug = f"{slug}-{(m.get('user_id') or '')[-4:]}"
        out[slug] = m
    return out


_PEOPLE_RE = re.compile(r"(?:(?<=^)|(?<=[\s(\[,;.!?]))@([a-z0-9][a-z0-9.\-]*[a-z0-9]|[a-z0-9])(?![\w@])", re.IGNORECASE)


def extract_people(text: str, directory: dict) -> tuple[str, list[str]]:
    """Removes the person/group tags from the text -> (clean text, [slugs in order]).
    Only known slugs (and "@team"/"@tutti") count; anything else is left untouched."""
    found = []

    def _sub(m):
        slug = m.group(1).lower().rstrip(".")
        if slug in directory or slug in GROUP_TAGS:
            if slug not in found:
                found.append(slug)
            return ""
        return m.group(0)

    clean = _PEOPLE_RE.sub(_sub, text or "")
    return re.sub(r"[ \t]{2,}", " ", clean).strip(), found
