"""Reports for the "artigiano" vertical (primo sopralluogo, later rapporto d'intervento):
a dictated/written description becomes a structured .docx, the client and the commessa
are recognized in (or added to) the Clienti list.

Same approach as vet_reports.py: the model only fills a fixed skeleton of sections /
fields from what was said (never inventing measures, prices or dates); who the client is
is resolved deterministically by the caller, not left to the model.
"""
import io
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import openai
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt

import usage_tracking as ut

logger = logging.getLogger(__name__)

MODEL = "gpt-4o"
FEATURE = "creazione_report"
LOCAL_TZ = ZoneInfo("Europe/Rome")

# Primo sopralluogo: a verbale structured as a record of the quality system (UNI EN ISO 9001:2015 §7.5 documented
# information, §8.2.2-8.2.3 the customer's requirements determined and reviewed), with the health & safety (ISO 45001,
# D.Lgs. 81/2008) and environmental (ISO 14001) aspects seen on site. Field names used elsewhere stay as they were
# ("Oggetto dell'intervento", "Lavori proposti", "Tempi indicativi", "Stima economica indicativa", "Note e prescrizioni").
SOPRALLUOGO_SECTIONS = [
    {"title": "1. Dati identificativi", "fields": ["Cliente", "Telefono", "Email", "Indirizzo del cantiere", "Riferimento commessa"]},   # (= CLIENT_SECTION)
    {"title": "2. Dati del sopralluogo", "fields": ["Data", "Eseguito da", "Presenti al sopralluogo", "Oggetto dell'intervento",
                                                    "Scopo del sopralluogo"]},
    {"title": "3. Requisiti del cliente", "fields": ["Esigenze e richieste del cliente", "Vincoli e condizioni (accessi, orari, tempi)",
                                                     "Riferimenti normativi applicabili"]},
    {"title": "4. Stato di fatto e rilievi", "fields": ["Descrizione dello stato attuale", "Misure e rilievi",
                                                        "Impianti / strutture esistenti", "Strumenti di misura utilizzati"]},
    {"title": "5. Valutazione tecnica", "fields": ["Fattibilità tecnica", "Criticità e non conformità riscontrate",
                                                   "Verifiche e approfondimenti necessari"]},
    {"title": "6. Sicurezza e ambiente", "fields": ["Rischi per la sicurezza rilevati", "Misure di prevenzione e DPI previsti",
                                                    "Aspetti ambientali e gestione dei rifiuti"]},
    {"title": "7. Proposta tecnica", "fields": ["Lavori proposti", "Materiali e componenti previsti", "Tempi indicativi",
                                                "Stima economica indicativa"]},
    {"title": "8. Azioni successive", "fields": ["Prossimi passi", "Documentazione da acquisire", "Note e prescrizioni"]},
]
# what the model must not write by itself: the app fills these (commessa, applicable rules)
APP_FILLED = {"Riferimento commessa"}

# the rules that apply to a kind of work - fixed and checked here, never written by the model; shown as indicative
# ("da confermare in progettazione"). Matched on the words of the dictation and of the commessa.
_NORMS = [
    (r"fotovoltaic|pannell[io] solar|\bfv\b|inverter|accumul", ["CEI 0-21 (connessione alla rete BT)", "Guida CEI 82-25 (impianti fotovoltaici)"]),
    (r"elettric|quadro|prese?\b|punti luce|illuminaz|differenzial|salvavita|messa a terra", ["CEI 64-8 (impianti elettrici utilizzatori BT)"]),
    (r"\bgas\b|caldaia|metano|gpl|piano cottura", ["UNI 7129 (impianti a gas per uso domestico)"]),
    (r"idraulic|idric|acqua sanitaria|scarich|tubazion|bagno|sanitari|doccia", ["UNI 9182 e UNI EN 806 (impianti idrici)"]),
    (r"condizionator|climatizz|pompa di calore|split|refrigerant", ["Regolamento (UE) 2024/573 (gas fluorurati)"]),
]
_IMPIANTI = r"impiant|fotovoltaic|caldaia|\bgas\b|elettric|idraulic|condizionator|climatizz|pompa di calore"


def applicable_norms(text: str) -> str:
    """The rules that apply to the work said (one per line), or "" when the kind of work isn't clear."""
    low = (text or "").lower()
    out = []
    for pat, norms in _NORMS:
        if re.search(pat, low):
            out += [n for n in norms if n not in out]
    if re.search(_IMPIANTI, low):
        out.append("D.M. 37/2008 (installazione degli impianti, dichiarazione di conformità)")
    if out:
        out.append("D.Lgs. 81/2008 (salute e sicurezza nei luoghi di lavoro)")
        return "\n".join(f"- {n}" for n in out) + "\n(Riferimenti indicativi, da confermare in fase di progettazione.)"
    return ""


# how each report is named in its document code (ISO 9001 §7.5.2: identification of the documented information)
DOC_PREFIX = {"sopralluogo": "VS", "intervento": "RI", "sal": "SAL", "fine_lavori": "VFL", "variante": "VAR", "commessa": "RC"}

CLIENT_SECTION = {"title": "1. Dati identificativi", "fields": ["Cliente", "Telefono", "Email", "Indirizzo del cantiere", "Riferimento commessa"]}

# The other ready models, revised the same way: records of the quality system (UNI EN ISO 9001:2015 - the clauses of each
# in QUALITY_CLAUSES), with the safety (ISO 45001, D.Lgs. 81/2008) and environmental (ISO 14001) aspects of the work.
# The names the app fills from the diary stay as they were ("Periodo di riferimento", "Ore impiegate", "Materiali impiegati",
# "Problemi riscontrati", "Tappe", "Data inizio lavori", "Data fine lavori", "Ore complessive", "Attività svolte", ...).

# Rapporto di intervento: one visit (a repair, a maintenance, an installation) - service provision, release, nonconformities
INTERVENTO_SECTIONS = [
    CLIENT_SECTION,
    {"title": "2. Dati dell'intervento", "fields": ["Data", "Eseguito da", "Orario", "Tipo di intervento", "Motivo della richiesta"]},
    {"title": "3. Diagnosi", "fields": ["Anomalie riscontrate", "Causa individuata"]},
    {"title": "4. Attività eseguite", "fields": ["Attività svolte", "Materiali utilizzati", "Ore di lavoro", "Strumenti di misura utilizzati"]},
    {"title": "5. Verifiche ed esito", "fields": ["Prove e verifiche eseguite", "Esito", "Non conformità residue o lavori da completare"]},
    {"title": "6. Sicurezza e ambiente", "fields": ["Misure di sicurezza adottate", "Materiali rimossi e smaltimento"]},
    {"title": "7. Indicazioni al cliente", "fields": ["Consigli al cliente", "Prossimi passi"]},
]

# Stato avanzamento lavori (SAL): where the job is - hours, materials, problems and tappe of the period also come from the
# commessa's diary when the dictation doesn't say them; monitoring, changes and corrective actions
SAL_SECTIONS = [
    CLIENT_SECTION,
    {"title": "2. Dati dello stato di avanzamento", "fields": ["Data", "Eseguito da", "Periodo di riferimento", "Percentuale di avanzamento"]},
    {"title": "3. Lavori del periodo", "fields": ["Lavori eseguiti", "Ore impiegate", "Materiali impiegati", "Tappe"]},
    {"title": "4. Controlli e verifiche", "fields": ["Controlli eseguiti nel periodo", "Esito dei controlli"]},
    {"title": "5. Criticità e modifiche", "fields": ["Problemi riscontrati", "Azioni correttive", "Varianti o lavori extra"]},
    {"title": "6. Sicurezza e ambiente", "fields": ["Sicurezza in cantiere", "Rifiuti prodotti e smaltimento"]},
    {"title": "7. Programmazione", "fields": ["Prossime attività", "Previsione di fine lavori"]},
    {"title": "8. Note", "fields": ["Note"]},
]

# Verbale di fine lavori e consegna: release of the work, the documents handed over (D.M. 37/2008), after-delivery
FINE_LAVORI_SECTIONS = [
    CLIENT_SECTION,
    {"title": "2. Dati dei lavori", "fields": ["Data", "Eseguito da", "Oggetto dei lavori", "Data inizio lavori", "Data fine lavori",
                                               "Ore complessive"]},
    {"title": "3. Lavori eseguiti", "fields": ["Lavori eseguiti", "Materiali e componenti installati"]},
    {"title": "4. Verifiche e collaudi", "fields": ["Verifiche e collaudi", "Esito del collaudo", "Strumenti di misura utilizzati"]},
    {"title": "5. Documentazione e conformità", "fields": ["Documentazione consegnata", "Riferimenti normativi applicabili"]},
    {"title": "6. Consegna e garanzia", "fields": ["Garanzia", "Istruzioni per il cliente", "Manutenzione consigliata"]},
    {"title": "7. Riserve", "fields": ["Riserve o lavori da completare"]},
    {"title": "8. Sicurezza e ambiente", "fields": ["Pulizia del cantiere e smaltimento dei rifiuti"]},
]

# Lavori extra / variante: a change to the agreed requirements, to be approved by the client before it is done
VARIANTE_SECTIONS = [
    CLIENT_SECTION,
    {"title": "2. Dati della variante", "fields": ["Data", "Eseguito da", "Oggetto", "Motivo della variante", "Richiesta da"]},
    {"title": "3. Descrizione della modifica", "fields": ["Descrizione dei lavori", "Materiali", "Effetti sui lavori previsti"]},
    {"title": "4. Effetti su tempi e costi", "fields": ["Tempi aggiuntivi", "Costo aggiuntivo indicativo"]},
    {"title": "5. Condizioni", "fields": ["Note e condizioni"]},
]

# the clauses of UNI EN ISO 9001:2015 each record answers to (shown at the end of the document)
QUALITY_CLAUSES = {
    "sopralluogo": "§7.5 informazioni documentate, §8.2 requisiti per prodotti e servizi",
    "intervento": "§7.5 informazioni documentate, §8.5.1 controllo dell'erogazione del servizio, §8.6 rilascio, "
                  "§8.7 controllo degli output non conformi",
    "sal": "§7.5 informazioni documentate, §8.5.1 controllo dell'erogazione del servizio, §8.5.6 controllo delle modifiche, "
           "§9.1.1 monitoraggio e misurazione",
    "fine_lavori": "§7.5 informazioni documentate, §8.6 rilascio di prodotti e servizi, §8.5.5 attività post-consegna",
    "variante": "§7.5 informazioni documentate, §8.2.4 modifiche ai requisiti, §8.5.6 controllo delle modifiche",
    "commessa": "§7.5 informazioni documentate, §9.1.1 monitoraggio, misurazione, analisi e valutazione",
}
# who signs for the client, by record
CLIENT_SIGN = {"fine_lavori": "Per accettazione e presa in consegna (il cliente)",
               "variante": "Per accettazione della variante (il cliente)"}


def quality_note(report_type: str) -> str:
    clauses = QUALITY_CLAUSES.get(report_type)
    if not clauses:
        return ""
    return (f"Modulo strutturato secondo i requisiti di registrazione della UNI EN ISO 9001:2015 ({clauses}); aspetti di "
            "sicurezza e ambiente secondo i principi di UNI EN ISO 45001 e UNI EN ISO 14001.")


# at most five ready models (plus the user's own uploaded ones)
BUILTIN_TEMPLATES = {
    "sopralluogo": {"name": "Primo sopralluogo", "sections": SOPRALLUOGO_SECTIONS,
                    "hint": "Sopralluogo dal signor Rossi in via Roma 5: impianto della cucina da rifare…"},
    "intervento": {"name": "Rapporto di intervento", "sections": INTERVENTO_SECTIONS,
                   "hint": "Oggi dai Rossi dalle 9 alle 11: sostituito il miscelatore della doccia, perdita risolta…"},
    "sal": {"name": "Stato avanzamento lavori", "sections": SAL_SECTIONS,
            "hint": "SAL del bagno dei Rossi: fatto il 60%, impianti finiti, la prossima settimana le piastrelle…"},
    "fine_lavori": {"name": "Verbale di fine lavori", "sections": FINE_LAVORI_SECTIONS,
                    "hint": "Fine lavori del bagno dei Rossi: tutto collaudato, consegnata la dichiarazione di conformità…"},
    "variante": {"name": "Lavori extra / variante", "sections": VARIANTE_SECTIONS,
                 "hint": "Variante per i Rossi: chiedono una presa in più in bagno, mezza giornata, circa 150 euro…"},
}

# report label <- Clienti list base field
CLIENT_FIELD_TO_LABEL = {"nome": "Cliente", "telefono": "Telefono", "email": "Email"}


def _track(resp, user_id: Optional[str], channel: str, status: str = "ok"):
    usage = getattr(resp, "usage", None) if resp is not None else None
    ut.fire_and_forget_llm_call(
        user_id=user_id, feature=FEATURE, channel=channel, trigger="utente",
        model=(getattr(resp, "model", None) if resp is not None else None) or MODEL, endpoint="chat.completions",
        input_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0, cached_input_tokens=0,
        output_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        status=status, request_id=getattr(resp, "id", None) if resp is not None else None,
    )


def find_matching_clients(text: str, clients: list, name_key: str) -> list:
    """Clients whose name appears in the text as whole words ("Rossi" also finds "Mario
    Rossi" when it's the only Rossi). Several distinct ones = the caller asks."""
    low = (text or "").lower()
    full, partial = [], []
    for c in clients:
        name = str((c.get("data") or {}).get(name_key) or "").strip()
        if not name:
            continue
        if re.search(rf"\b{re.escape(name.lower())}\b", low):
            full.append(c)
            continue
        words = [w for w in re.findall(r"[\wàèéìòù']+", name.lower()) if len(w) >= 4]
        if words and any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            partial.append(c)
    return full or partial


async def interpret(text: str, sections: list, user_name: str = "", user_id: Optional[str] = None, channel: str = "web",
                    report_name: str = "", context: str = "", photos: int = 0) -> dict:
    """{"sections": [{"title", "fields": {label: value}}], "client": {...}, "job_title": "..."}
    context: what the app already knows of the commessa (its title, description, survey notes) - true data, usable as the text;
    photos: how many photos go in the report (shown in its own section, never described here)."""
    today = datetime.now(LOCAL_TZ)
    skeleton = json.dumps([{"title": s["title"], "fields": s["fields"]} for s in sections], ensure_ascii=False)
    system = (
        "Sei l'assistente di un'impresa artigiana (impianti elettrici, idraulici, edilizia, manutenzioni). Ricevi "
        "il resoconto dettato o scritto di un intervento o di un sopralluogo e lo strutturi in un report "
        f"professionale da consegnare al cliente. Oggi è {today.strftime('%d/%m/%Y')}; il report lo firma {user_name or 'il titolare'}.\n"
        + (f"Tipo di report: {report_name}.\n" if report_name else "") + "\n"
        f"Schema da compilare (rispetta ESATTAMENTE titoli e nomi dei campi):\n{skeleton}\n\n"
        "Regole:\n"
        "1. Compila SOLO con ciò che è detto nel testo. Se un'informazione manca lascia la stringa vuota: NON inventare "
        "misure, quantità, prezzi, tempi o date. Se non c'è una data, usa la data di oggi solo nel campo 'Data'.\n"
        "2. Linguaggio tecnico e professionale del settore, frasi impersonali e concise (es. 'Si rileva…', "
        "'Si propone…'), niente prima persona, niente commenti fuori dai campi.\n"
        "3. Liste di lavori o materiali: una voce per riga, preceduta da '- '.\n"
        "3b. È una registrazione del sistema qualità (UNI EN ISO 9001): scrivi fatti rilevati e decisioni, non opinioni. "
        "'Criticità e non conformità riscontrate': solo ciò che è detto come problema o non a norma. 'Prossimi passi': un'azione per "
        "riga, con chi la fa e la scadenza SOLO se dette. 'Rischi per la sicurezza', 'Misure di prevenzione e DPI', 'Aspetti "
        "ambientali e gestione dei rifiuti', 'Strumenti di misura utilizzati', 'Presenti al sopralluogo': solo se detti. "
        "'Riferimenti normativi applicabili': solo norme citate nel testo (le altre le aggiunge l'app). 'Riferimento commessa': "
        "lascialo vuoto. Allo stesso modo, solo se detti: 'Causa individuata', 'Prove e verifiche eseguite', 'Controlli eseguiti "
        "nel periodo', 'Esito dei controlli', 'Azioni correttive', 'Esito del collaudo', 'Documentazione consegnata', 'Garanzia', "
        "'Manutenzione consigliata', 'Richiesta da', 'Effetti sui lavori previsti', 'Sicurezza in cantiere', 'Rifiuti prodotti e "
        "smaltimento', 'Pulizia del cantiere e smaltimento dei rifiuti'.\n"
        + ("4. Dopo il resoconto trovi i DATI DELLA COMMESSA già registrati nell'app (titolo, descrizione, note del sopralluogo): "
           "sono veri, usali come il resoconto per compilare i campi pertinenti. Non aggiungere nulla che non sia scritto lì o nel resoconto.\n"
           if context else "")
        + (f"5. Al report sono allegate {photos} foto, in una sezione 'Documentazione fotografica' a parte: puoi rimandarvi "
           "('si veda la documentazione fotografica') ma NON descrivere cosa mostrano se il testo non lo dice.\n" if photos else "")
        + "Rispondi SOLO con JSON: {\"sections\": [{\"title\": \"...\", \"fields\": {\"Nome campo\": \"valore\"}}], "
        "\"client\": {\"name\": \"nome e cognome o ragione sociale del cliente, se detto\", \"phone\": \"\", \"email\": \"\", "
        "\"address\": \"indirizzo del cantiere, se detto\"}, \"job_title\": \"titolo breve dei lavori (max 8 parole), "
        "es. 'Rifacimento impianto elettrico cucina'\", \"summary\": \"riassunto del report in 1-3 frasi brevi (max 300 "
        "caratteri) per il diario della commessa: cosa si è rilevato, cosa si propone o si è fatto, i prossimi passi. Solo "
        "ciò che è nel testo, senza dati del cliente\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=4096, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": text + (f"\n\n--- DATI DELLA COMMESSA (già registrati) ---\n{context}" if context else "")}],
        )
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    if not m:
        raise ValueError("Nessun JSON nella risposta del modello")
    parsed = json.loads(m.group(0))
    by_title = {s.get("title"): s for s in parsed.get("sections", []) if isinstance(s, dict)}
    out = []
    for sk in sections:
        got = (by_title.get(sk["title"]) or {}).get("fields") or {}
        out.append({"title": sk["title"], "fields": {f: str(got.get(f) or "").strip() for f in sk["fields"]}})
    cl = parsed.get("client") if isinstance(parsed.get("client"), dict) else {}
    return {
        "sections": out,
        "client": {k: str(cl.get(k) or "").strip() for k in ("name", "phone", "email", "address")},
        "job_title": str(parsed.get("job_title") or "").strip()[:80],
        "summary": str(parsed.get("summary") or "").strip()[:400],
    }


# fields that are not the report's content: who the client is, who signed it, when
_NOT_CONTENT = {"Cliente", "Telefono", "Email", "Indirizzo del cantiere", "Data", "Eseguito da", "Riferimento commessa",
                "Presenti al sopralluogo", "Strumenti di misura utilizzati", "Riferimenti normativi applicabili",
                "Scopo del sopralluogo"}


def summary_of(sections: list, limit: int = 300) -> str:
    """A short summary from the report's own fields, when the model gave none: the first filled
    fields that say what the report is about (not the client's data, the date or the signature)."""
    out = ""
    for sec in sections or []:
        for label, value in (sec.get("fields") or {}).items():
            if label in _NOT_CONTENT or re.search(r"telefon|e-?mail|cellulare", label, re.I):
                continue
            rows = [r.strip() for r in str(value or "").splitlines() if r.strip()]
            v = ", ".join(r[2:].strip() if r.startswith("- ") else r.rstrip(".") for r in rows)
            if not v:
                continue
            part = f"{label}: {v.rstrip('.')}."
            if not out:   # the first one always, cut if too long
                out = part if len(part) <= limit else part[:limit].rsplit(" ", 1)[0] + "…"
            elif len(out) + 1 + len(part) <= limit:
                out += " " + part
            else:
                return out
    return out


async def revise(sections: list, instruction: str, user_id: Optional[str] = None, channel: str = "web") -> dict:
    """A change asked on a report already made ("togli la stima", "il telefono è 333...", "aggiungi
    che serve il permesso del condominio"): only what is asked changes, the rest stays word for
    word. -> {"sections", "client": {name, phone, email, address} only for what the request
    changes, "job_title": new one or ""}"""
    current = json.dumps([{"title": s["title"], "fields": s["fields"]} for s in sections], ensure_ascii=False)
    system = (
        "Sei l'assistente di un'impresa artigiana. Hai un report GIÀ COMPILATO (JSON qui sotto) e l'utente chiede "
        "una MODIFICA. Applica SOLO quello che chiede:\n"
        "- i campi che la richiesta non tocca restano IDENTICI, parola per parola;\n"
        "- non aggiungere, completare o inventare nulla che la richiesta non dica (niente dati di esempio, niente "
        "nomi, misure, prezzi o date nuove);\n"
        "- 'aggiungi ...' aggiunge al campo giusto senza cancellare quello che c'è; 'togli/elimina ...' svuota o "
        "toglie solo quella parte; 'cambia/correggi X in Y' sostituisce;\n"
        "- stessi titoli di sezione e stessi nomi di campo, nello stesso ordine.\n"
        "Se la richiesta cambia i dati del cliente (nome, telefono, email, indirizzo del cantiere), mettili anche in "
        "\"client\" (solo quelli cambiati, gli altri stringa vuota). Se cambia l'oggetto dei lavori, dai un nuovo "
        "\"job_title\" breve, altrimenti stringa vuota.\n\n"
        f"REPORT ATTUALE:\n{current}\n\n"
        "Rispondi SOLO con JSON: {\"sections\": [{\"title\": \"...\", \"fields\": {\"Nome campo\": \"valore\"}}], "
        "\"client\": {\"name\": \"\", \"phone\": \"\", \"email\": \"\", \"address\": \"\"}, \"job_title\": \"\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=4096, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": instruction}],
        )
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    parsed = json.loads(m.group(0)) if m else {}
    by_title = {s.get("title"): s for s in parsed.get("sections", []) if isinstance(s, dict)}
    out = []
    for sk in sections:   # the skeleton is the report's own: a field the model dropped keeps its value
        got = (by_title.get(sk["title"]) or {}).get("fields")
        got = got if isinstance(got, dict) else {}
        out.append({"title": sk["title"], "fields": {f: (str(got[f]).strip() if f in got and got[f] is not None else v)
                                                     for f, v in sk["fields"].items()}})
    cl = parsed.get("client") if isinstance(parsed.get("client"), dict) else {}
    return {"sections": out, "client": {k: str(cl.get(k) or "").strip() for k in ("name", "phone", "email", "address")},
            "job_title": str(parsed.get("job_title") or "").strip()[:80]}


def changed_fields(old: list, new: list) -> list:
    """["Sezione › Campo", ...] whose value differs."""
    old_map = {(s["title"], f): v for s in old for f, v in s["fields"].items()}
    return [f"{s['title']} › {f}" for s in new for f, v in s["fields"].items() if (old_map.get((s["title"], f)) or "") != (v or "")]


def said_in(name: str, text: str) -> bool:
    """The client name the model read is really in the text (at least one of its words of 3+
    letters): a name the model made up must never become a client."""
    low = (text or "").lower()
    words = [w for w in re.findall(r"[\wàèéìòù']+", (name or "").lower()) if len(w) >= 3]
    return bool(words) and any(re.search(rf"\b{re.escape(w)}\b", low) for w in words)


def clear_field(sections: list, label: str) -> None:
    for s in sections:
        if label in s["fields"]:
            s["fields"][label] = ""


def set_field(sections: list, label: str, value: str, overwrite: bool = True) -> None:
    for s in sections:
        if label in s["fields"] and value and (overwrite or not s["fields"][label]):
            s["fields"][label] = value


def _page_field(paragraph, code: str) -> None:
    """A Word field (PAGE / NUMPAGES) in the paragraph: the page numbers, kept right by Word."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, code), ("separate", None), (None, None), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), kind); run._r.append(el)
        elif text:
            el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = f" {text} "; run._r.append(el)
        else:
            el = OxmlElement("w:t"); el.text = "1"; run._r.append(el)
    run.font.size = Pt(8)


def _shade(cell, hex_fill: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(shd)


def add_logo(doc, logo: Optional[bytes]) -> None:
    """The organization's logo at the top of every page (the page header), left, 1.6 cm tall (at most 6 cm wide)."""
    if not logo:
        return
    try:
        from PIL import Image
        w, h = Image.open(io.BytesIO(logo)).size
        height = Cm(1.6) if w / max(h, 1) * 1.6 <= 6 else Cm(6 * h / max(w, 1))
        p = doc.sections[0].header.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        p.add_run().add_picture(io.BytesIO(logo), height=height)
    except Exception:
        logger.exception("report logo not added")


def build_docx(title: str, client_name: Optional[str], job_title: Optional[str], sections: list, company: str = "",
               photos: Optional[list] = None, doc_info: Optional[dict] = None, logo: Optional[bytes] = None) -> bytes:
    """photos: [{"bytes": jpeg, "caption": text}] - the "Documentazione fotografica", before the signatures.
    doc_info: the document's identification (ISO 9001 §7.5): {"code", "revision", "date", "commessa", "revisions":
    [{"rev", "date", "what"}], "quality_note": bool} - a control block on top, the code and the pages in the footer,
    the revisions' history, and the signatures of who wrote it, who approved it and the client.
    logo: the organization's logo (PNG/JPEG bytes), on top of every page."""
    doc = Document()
    add_logo(doc, logo)
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    info = doc_info or {}
    if info:
        sec0 = doc.sections[0]
        sec0.left_margin = sec0.right_margin = Cm(2)
        sec0.top_margin, sec0.bottom_margin = Cm(1.8), Cm(1.8)
        # the control block: who issues it and what it is | its number, revision, date, commessa
        head = doc.add_table(rows=4, cols=2)
        head.style = "Table Grid"
        left = head.cell(0, 0).merge(head.cell(3, 0))
        left.text = ""
        p = left.paragraphs[0]
        r = p.add_run(company or ""); r.bold = True; r.font.size = Pt(11)
        p2 = left.add_paragraph(); r2 = p2.add_run(title.upper()); r2.bold = True; r2.font.size = Pt(15)
        if job_title or client_name:
            p3 = left.add_paragraph(" · ".join(x for x in (client_name and f"Cliente: {client_name}", job_title and f"Lavori: {job_title}") if x))
            p3.runs[0].italic = True; p3.runs[0].font.size = Pt(9)
        rows = [("Documento n.", info.get("code") or "-"), ("Revisione", f"{int(info.get('revision') or 0):02d}"),
                ("Data di emissione", info.get("date") or "-"), ("Commessa", info.get("commessa") or "-")]
        for i, (label, value) in enumerate(rows):
            c = head.cell(i, 1)
            c.text = ""
            pr = c.paragraphs[0]
            lr = pr.add_run(f"{label}: "); lr.bold = True; lr.font.size = Pt(9)
            vr = pr.add_run(value); vr.font.size = Pt(9)
        head.autofit = False
        head.columns[0].width, head.columns[1].width = Cm(10.5), Cm(6.5)
        for row in head.rows:
            row.cells[0].width, row.cells[1].width = Cm(10.5), Cm(6.5)
        # the footer: the code, the revision and the pages, on every page
        fp = sec0.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        fr = fp.add_run(f"{info.get('code') or title} · Rev. {int(info.get('revision') or 0):02d} · Pag. ")
        fr.font.size = Pt(8)
        _page_field(fp, "PAGE")
        fr2 = fp.add_run(" di "); fr2.font.size = Pt(8)
        _page_field(fp, "NUMPAGES")
        doc.add_paragraph()
    else:
        if company:
            p = doc.add_paragraph(company)
            p.runs[0].bold = True
        heading = doc.add_heading(title, level=0)
        for run in heading.runs:
            run.font.size = Pt(20)
        sub = doc.add_paragraph(" · ".join(x for x in (client_name and f"Cliente: {client_name}", job_title and f"Lavori: {job_title}") if x)
                                or "Cliente: non indicato")
        sub.runs[0].italic = True
    n_sec = 0
    for sec in sections:
        if not any(v for v in sec["fields"].values()):
            continue   # a section nobody talked about stays out of the client's copy
        n_sec += 1
        # a record: the sections shown numbered in order (an empty one leaves no gap)
        plain = re.sub(r"^\d+\.\s*", "", sec["title"])
        doc.add_heading(f"{n_sec}. {plain}" if info else sec["title"], level=1)
        table = doc.add_table(rows=0, cols=2)
        table.style = "Table Grid" if info else "Light Grid Accent 1"
        if info:
            table.autofit = False
            table.columns[0].width, table.columns[1].width = Cm(5.5), Cm(11.5)
        for label, value in sec["fields"].items():
            if info and not value:
                continue   # a record: only what was found, said or decided
            row = table.add_row()
            row.cells[0].text = label
            row.cells[1].text = value or "-"
            if info:
                row.cells[0].width, row.cells[1].width = Cm(5.5), Cm(11.5)
                _shade(row.cells[0], "F2F2F2")
            for p in row.cells[0].paragraphs:
                for r in p.runs:
                    r.bold = True
    shots = [p for p in (photos or []) if p.get("bytes")]
    if shots:
        n_sec += 1
        doc.add_heading((f"{n_sec}. " if info else "") + "Documentazione fotografica", level=1)
        for i, ph in enumerate(shots, 1):
            try:
                doc.add_picture(io.BytesIO(ph["bytes"]), width=Cm(14))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            except Exception:
                logger.exception("report photo not added")
                continue
            cap = doc.add_paragraph(f"Foto {i}" + (f" – {ph['caption']}" if ph.get("caption") else ""))
            cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
            cap.runs[0].italic = True
            cap.runs[0].font.size = Pt(9)
    if info and info.get("revisions"):   # ISO 9001 §7.5.3: the changes, identified
        doc.add_heading("Stato delle revisioni", level=1)
        rv = doc.add_table(rows=1, cols=3)
        rv.style = "Table Grid"
        rv.autofit = False
        for c, t in zip(rv.rows[0].cells, ("Rev.", "Data", "Descrizione della modifica")):
            c.text = t
            _shade(c, "F2F2F2")
            for r in c.paragraphs[0].runs:
                r.bold = True
        for x in info["revisions"]:
            cells = rv.add_row().cells
            cells[0].text, cells[1].text, cells[2].text = f"{int(x.get('rev') or 0):02d}", x.get("date") or "", x.get("what") or ""
        for row in rv.rows:
            row.cells[0].width, row.cells[1].width, row.cells[2].width = Cm(1.5), Cm(3), Cm(12.5)
    # signatures: room to sign on the printed copy (no digital signature for now)
    # the signatures stay together, on one page, with the place and date
    for t in ("", "Luogo e data: ________________________________", ""):
        doc.add_paragraph(t).paragraph_format.keep_with_next = True
    heads = (["Redatto da (il tecnico)", "Verificato e approvato da", info.get("client_sign") or "Per presa visione (il cliente)"] if info
             else ["Firma del tecnico", "Firma del cliente per presa visione"])
    sig = doc.add_table(rows=2, cols=len(heads))
    if info:
        sig.autofit = False
        for i in range(len(heads)):
            sig.columns[i].width = Cm(17 / len(heads))
            for r in range(2):
                sig.cell(r, i).width = Cm(17 / len(heads))
    for i, h in enumerate(heads):
        sig.cell(0, i).text = h
        sig.cell(1, i).text = "\n\n" + "_" * (22 if info else 30)
        for p in sig.cell(0, i).paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for r in p.runs:
                r.bold = True
                if info:
                    r.font.size = Pt(9)
        for p in sig.cell(1, i).paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for p in sig.cell(0, i).paragraphs:
            p.paragraph_format.keep_with_next = True
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    for row in sig.rows:   # a row never split across two pages
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    if info.get("quality_note"):
        q = doc.add_paragraph()
        q.paragraph_format.space_before = Pt(14)
        qr = q.add_run(info["quality_note"] if isinstance(info["quality_note"], str) else quality_note("sopralluogo"))
        qr.italic = True
        qr.font.size = Pt(7.5)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ---- report di commessa ----
# Not dictated: made from the commessa's diary for a period, with the parts the user picks.
# Hours, problems, materials, milestones and costs are copied from the data as they are; the
# model only writes the summary of the job's state and of the work done, from those entries.

COMMESSA_REPORT = {"key": "commessa", "name": "Report di commessa",
                   "hint": "Report della commessa bagno dei Rossi di ottobre, metti in evidenza i ritardi"}
# (key, section title) in the report's order
COMMESSA_PARTS = [("stato", "Riassunto stato commessa"), ("attivita", "Lavori svolti"), ("ore", "Ore lavorate"),
                  ("problemi", "Problematiche"), ("materiali", "Materiali"), ("milestone", "Tappe"), ("costi", "Costi")]
COMMESSA_DEFAULT = ["stato", "ore", "problemi"]
_PART_WORDS = {"stato": r"riassunt|\bstato (?:della|dei|del|commessa|lavori|avanzamento)|andamento|situazion", "attivita": r"lavori svolti|attivit|cosa (?:abbiamo|è stato) fatto",
               "ore": r"\bore\b|\bor[ae]\s+lavo|orari|presenz|per (?:lavorator|operai|persona)", "problemi": r"problem|criticit|anomali", "materiali": r"material",
               "milestone": r"milestone|scadenz|tappe", "costi": r"\bcost[oi]\b|\bspes[ae]\b|margin|preventiv"}

MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
          "novembre", "dicembre"]
_NUM_WORDS = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8,
              "nove": 9, "dieci": 10, "quindici": 15, "venti": 20, "trenta": 30}


def asks_commessa_report(text: str) -> bool:
    """The request is for a report di commessa ("fammi il report della commessa impianto elettrico"),
    whatever type is selected: it is made from the diary, never as a dictated report."""
    low = " ".join((text or "").lower().split())
    return bool(re.search(r"\b(?:report|resoconto|riepilogo|relazione)\s+(?:di|della|dell[a']|del|sulla|sul)\s*(?:commess[ae]|cantier[ei])\b", low))


# which report the message asks for, whatever type is selected in the chat: the first cue
# said wins ("sopralluogo dai Rossi per una variante" is a sopralluogo)
_TYPE_CUES = [
    ("sopralluogo", r"sopra+l+uog"),
    ("intervento", r"\bintervent[oi]\b|riparazion|manutenzion|installazion|\bguast[oi]\b"),
    ("sal", r"\bs\.?a\.?l\.?(?=\s|$|[,.:;!?])|stato (?:di |d')?avanzamento"),
    ("fine_lavori", r"fine (?:dei )?lavori|verbale di (?:fine|consegna)|consegna (?:dei )?lavori|chiusura (?:dei )?lavori|lavori (?:finiti|terminati|conclusi)"),
    ("variante", r"\bvariant[ei]\b|lavori (?:extra|aggiuntivi|in pi[uù])|extra lavori"),
]


def detect_report_type(text: str, custom: Optional[list] = None) -> Optional[str]:
    """The report type the message asks for -> a BUILTIN_TEMPLATES key, "commessa", the id of
    one of the user's own models named in it ({"id", "name"}), or None (the selection decides)."""
    low = " ".join((text or "").lower().split())
    if not low:
        return None
    if asks_commessa_report(low):
        return COMMESSA_REPORT["key"]
    for t in custom or []:
        name = " ".join(str(t.get("name") or "").lower().split())
        if len(name) >= 4 and re.search(rf"\b{re.escape(name)}\b", low):
            return t["id"]
    hits = [(m.start(), key) for key, rx in _TYPE_CUES for m in [re.search(rx, low)] if m]
    return min(hits)[1] if hits else None


def parts_from_text(text: str) -> list:
    """The parts named in the request ("solo ore e problemi"), in the report's order."""
    low = (text or "").lower()
    return [k for k, _ in COMMESSA_PARTS if re.search(_PART_WORDS[k], low)]


def _month_end(y: int, m: int) -> date:
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def _day(d: str, m: str, y: Optional[str], today: date) -> Optional[date]:
    try:
        year = int(y) + (2000 if y and len(y) == 2 else 0) if y else today.year
        out = date(year, int(m), int(d))
    except ValueError:
        return None
    return out if y or out <= today else date(year - 1, int(m), int(d))   # "dal 20/12" in January: last year's


def parse_period(text: str, today: date) -> Optional[tuple]:
    """A period said in the request -> (from, to) dates, or None (the whole commessa).
    "dal 1/10 al 15/10", "dal 3 al 20 ottobre", "dal 5 settembre", "ottobre", "di settembre 2026",
    "ultima settimana", "ultimi 15 giorni", "ultimo mese", "mese scorso", "questo mese",
    "settimana scorsa", "questa settimana", "oggi", "ieri"."""
    low = " ".join((text or "").lower().split())
    mon = "|".join(MONTHS)
    m = re.search(r"\bdal(?:l')?\s*(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\s+al(?:l')?\s*(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?", low)
    if m:
        a, b = _day(m[1], m[2], m[3], today), _day(m[4], m[5], m[6] or m[3], today)
        if a and b:
            return (a, b) if a <= b else (b, a)
    m = re.search(rf"\bdal(?:l')?\s*(\d{{1,2}})(?:\s+({mon}))?(?:\s+(\d{{4}}))?\s+al(?:l')?\s*(\d{{1,2}})\s+({mon})(?:\s+(\d{{4}}))?", low)
    if m:
        y = m[6] or m[3]
        a = _day(m[1], str(MONTHS.index(m[2] or m[5]) + 1), y, today)
        b = _day(m[4], str(MONTHS.index(m[5]) + 1), y, today)
        if a and b:
            return (a, b) if a <= b else (b, a)
    m = re.search(rf"\bdal(?:l')?\s*(\d{{1,2}})(?:[/.-](\d{{1,2}})(?:[/.-](\d{{2,4}}))?|\s+({mon})(?:\s+(\d{{4}}))?)", low)
    if m:
        a = _day(m[1], m[2], m[3], today) if m[2] else _day(m[1], str(MONTHS.index(m[4]) + 1), m[5], today)
        if a:
            return (a, today)
    if re.search(r"\boggi\b", low):
        return (today, today)
    if re.search(r"\bieri\b", low):
        return (today - timedelta(days=1),) * 2
    m = re.search(r"\bultim[ie]\s+(\d+|" + "|".join(_NUM_WORDS) + r")\s+(giorni|settimane|mesi)\b", low)
    if m:
        n = int(m[1]) if m[1].isdigit() else _NUM_WORDS[m[1]]
        days = n * {"giorni": 1, "settimane": 7, "mesi": 30}[m[2]]
        return (today - timedelta(days=days - 1), today)
    if re.search(r"\b(?:settimana scorsa|scorsa settimana)\b", low):
        start = today - timedelta(days=today.weekday() + 7)
        return (start, start + timedelta(days=6))
    if re.search(r"\b(?:questa settimana|settimana (?:in corso|corrente|attuale))\b", low):
        return (today - timedelta(days=today.weekday()), today)
    if re.search(r"\bultima settimana\b", low):
        return (today - timedelta(days=6), today)
    if re.search(r"\b(?:mese scorso|scorso mese)\b", low):
        end = today.replace(day=1) - timedelta(days=1)
        return (end.replace(day=1), end)
    if re.search(r"\b(?:questo mese|mese (?:in corso|corrente|attuale))\b", low):
        return (today.replace(day=1), today)
    if re.search(r"\bultimo mese\b", low):
        return (today - timedelta(days=29), today)
    # a month on its own: "di ottobre", "ottobre 2026", "nel mese di settembre" (not "il 3 ottobre")
    m = re.search(rf"(?<!\d\s)(?<!\d)\b({mon})\b(?:\s+(\d{{4}}))?", low)
    if m:
        mi = MONTHS.index(m[1]) + 1
        y = int(m[2]) if m[2] else (today.year if mi <= today.month else today.year - 1)
        return (date(y, mi, 1), min(_month_end(y, mi), today))
    return None


def period_label(start: date, end: date) -> str:
    f = lambda d: d.strftime("%d/%m/%Y")
    return f"il {f(start)}" if start == end else f"dal {f(start)} al {f(end)}"


async def commessa_summary(commessa: dict, period: str, diary: str, facts: str, wants: list, request: str = "",
                           user_id: Optional[str] = None, channel: str = "web") -> dict:
    """The two written parts of a report di commessa, from the diary only:
    {"stato": "the job's state in the period", "attivita": "- the work done, one line each"}."""
    keys = [k for k in ("stato", "attivita") if k in wants]
    if not keys:
        return {}
    ask = {"stato": "\"stato\": riassunto dello stato della commessa nel periodo, 3-6 frasi: a che punto sono i lavori, "
                    "cosa è stato fatto, problemi aperti e ritardi, cosa resta da fare (se il diario lo dice)",
           "attivita": "\"attivita\": i lavori svolti nel periodo, una voce per riga preceduta da '- ', raggruppando i "
                       "lavori simili; con la data (gg/mm) quando serve"}
    system = (
        "Sei l'assistente di un'impresa artigiana. Scrivi parti di un REPORT DI COMMESSA da consegnare al cliente o da "
        "tenere in archivio, usando SOLO i dati qui sotto (scheda della commessa e voci del suo diario di cantiere nel "
        "periodo). Non inventare lavori, date, quantità, nomi o percentuali che non ci sono. Linguaggio professionale, "
        "frasi impersonali e concise, niente prima persona. Se nel periodo non ci sono voci, dillo in una frase.\n"
        + (f"L'utente chiede di tenere conto di questo (solo per cosa evidenziare, non è un dato): «{request[:500]}»\n" if request else "")
        + f"\nCOMMESSA: {commessa.get('title')} · cliente {commessa.get('client_name') or '-'} · stato {commessa.get('stato') or '-'}"
        + (f" · inizio {commessa['data_inizio']}" if commessa.get("data_inizio") else "")
        + (f"\nDescrizione: {commessa['descrizione']}" if commessa.get("descrizione") else "")
        + f"\nPERIODO DEL REPORT: {period}\nDATI DEL PERIODO: {facts or '-'}\nDIARIO DEL PERIODO:\n{diary or '(nessuna voce)'}\n\n"
        "Rispondi SOLO con JSON: {" + ", ".join(ask[k] for k in keys) + "}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=2048, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": "Scrivi le parti del report."}],
        )
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    parsed = json.loads(m.group(0)) if m else {}
    return {k: str(parsed.get(k) or "").strip() for k in keys}
