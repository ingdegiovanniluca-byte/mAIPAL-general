"""@agenti in chat: splitting a message into the main part and the tagged pieces.
Run with: python -m pytest tests/test_mentions.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mentions import split_mentions  # noqa: E402


def test_main_text_and_one_tag():
    main, parts = split_mentions("Visitato Fester, terapia 7 giorni. @task richiamare la padrona giovedì")
    assert main == "Visitato Fester, terapia 7 giorni."
    assert parts == [{"agent": "task_todo", "tag": "task", "text": "richiamare la padrona giovedì"}]


def test_several_tags_each_get_their_piece():
    main, parts = split_mentions("Info cliente Rossi. @task chiamarlo lunedì @diario oggi ho visto Rossi @lista aggiungi Rossi ai clienti")
    assert main == "Info cliente Rossi."
    assert [(p["agent"], p["text"]) for p in parts] == [
        ("task_todo", "chiamarlo lunedì"), ("journal", "oggi ho visto Rossi"), ("list_update", "aggiungi Rossi ai clienti")]


def test_email_is_not_a_tag():
    main, parts = split_mentions("scrivi a mario@task.it per il preventivo")
    assert parts == [] and main == "scrivi a mario@task.it per il preventivo"


def test_unknown_name_is_not_a_tag():
    assert split_mentions("ci vediamo @ casa @mario")[1] == []


def test_spoken_forms():
    main, parts = split_mentions("ho visitato Fester agente task: richiamare la padrona giovedì")
    assert main == "ho visitato Fester" and parts[0]["agent"] == "task_todo" and parts[0]["text"] == "richiamare la padrona giovedì"
    assert split_mentions("nota importante chiocciola task ricordami la bolletta")[1][0]["text"] == "ricordami la bolletta"


def test_tag_at_start_and_case_insensitive():
    main, parts = split_mentions("@Task comprare il cibo del gatto")
    assert main == "" and parts[0] == {"agent": "task_todo", "tag": "task", "text": "comprare il cibo del gatto"}


def test_empty_piece_is_dropped_and_aliases():
    assert split_mentions("salva questo @task")[1] == []
    assert split_mentions("x @promemoria domani")[1][0]["agent"] == "task_todo"
    assert split_mentions("x @azione ogni lunedì alle 9 svuota la lista")[1][0]["agent"] == "scheduled_action"
    assert split_mentions("x @to-do comprare pane")[1][0]["text"] == "comprare pane"


from mentions import slugify, people_directory, extract_people  # noqa: E402


def test_people_slugs_and_extraction():
    members = [{"user_id": "u2", "name": "Mario Rossi"}, {"user_id": "u1", "name": "Giulia Bianchì"}, {"user_id": "u3", "name": "Mario Rossi"}]
    d = people_directory(members)
    assert set(d) == {"giulia.bianchi", "mario.rossi", "mario.rossi-u3"}
    assert slugify("Ánna  D'Amico") == "anna.d.amico"
    clean, found = extract_people("Il codice del cancello è 4521 @mario.rossi @team, grazie", d)
    assert clean == "Il codice del cancello è 4521 , grazie" and found == ["mario.rossi", "team"]
    # agent tags, e-mails and unknown names are left alone
    clean, found = extract_people("scrivi a mario@rossi.it @task chiamare @sconosciuto", d)
    assert found == [] and "@task" in clean and "mario@rossi.it" in clean and "@sconosciuto" in clean


def test_people_tag_at_sentence_end():
    d = people_directory([{"user_id": "u1", "name": "Luca"}])
    assert extract_people("condividi con @luca.", d) == ("condividi con .", ["luca"])
