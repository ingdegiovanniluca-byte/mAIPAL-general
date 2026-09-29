"""@agenti nella chat: "...informazioni sul paziente... @task richiamare la padrona giovedì".

The text before the first tag goes to the action selected in the chat (the main agent);
each tag's piece - up to the next tag - goes to that agent, which also receives the whole
message as context. Spoken forms work too, since "@" can't be dictated: "agente task ...",
"chiocciola task ..." (how speech-to-text writes "@"). An e-mail address such as
mario@gmail.com is never a tag: "@" must start a word and be followed by an agent name.

The same rules are mirrored in frontend/src/lib/mentions.js (menu, chips, highlighting).
"""
import re

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
