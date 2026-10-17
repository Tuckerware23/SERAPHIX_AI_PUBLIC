"""Seraphix v2.8.3: local, read-only evidence retrieval and conservative book answers."""
import json
from seraphix_config import SETTINGS
import math
import re
from collections import Counter
from pathlib import Path

INDEX = Path('Memory/Book_Index/chunks.json')
STOP = set('the a an and or of in on to for from with is are was were be been it its this that i you your my we they he she his her their what who how why does do did tell explain about book manuscript character chapter story please seraphix'.split())

def tokens(s):
    return [x for x in re.findall(r"[a-z0-9']+", s.lower()) if len(x)>2 and x not in STOP]

def load(base):
    p=Path(base)/INDEX
    if not p.is_file():
        raise FileNotFoundError(f'Manuscript index missing: {p}. Run seraphix_book_reader.py first.')
    data=json.loads(p.read_text(encoding='utf-8'))
    chunks=data.get('chunks')
    if not isinstance(chunks,list) or not chunks:
        raise ValueError('Book index is empty.')
    return chunks

def locate(ch):
    st=ch.get('start') or {}
    return f"paragraph {st['paragraph']}" if 'paragraph' in st else f"table {st.get('table','?')}, row {st.get('row','?')}"

def search(question, base, limit=7):
    chunks=load(base)
    q=Counter(tokens(question))
    if not q:return []
    docs=[Counter(tokens(str(c.get('text','')))) for c in chunks]
    df=Counter()
    for d in docs:df.update(d.keys())
    ranked=[]
    for ch,doc in zip(chunks,docs):
        score=sum((1+math.log(doc[t]))*math.log(1+(len(chunks)+1)/(df[t]+1))*min(n,2) for t,n in q.items() if doc[t])
        if score:ranked.append((score,ch))
    ranked.sort(key=lambda x:x[0],reverse=True)
    return [ch for _,ch in ranked[:limit]]


def _matches_question(rule, question):
    return all(term.casefold() in question.casefold() for term in rule["question_terms"])


def evidence_for_identity(base):
    """Configured source-pattern hits only; no embedded story facts."""
    chunks = load(base)
    return {
        str(index): [ch for ch in chunks if re.search(
            rule["source_pattern"], str(ch.get("text", "")), re.I)][:3]
        for index, rule in enumerate(SETTINGS["identity_rules"])
    }


def quote_context(ch, max_chars=2400):
    return f"[Book chunk {ch.get('id', '?')}; begins at {locate(ch)}]\n{str(ch.get('text', ''))[:max_chars]}"


def build_evidence(question, base):
    """Legacy chunk retrieval with optional trusted configuration priorities."""
    chunks = load(base)
    selected = search(question, base, limit=9)
    priority = []
    for rule in SETTINGS["retrieval_rules"]:
        if _matches_question(rule, question):
            priority.extend([ch for ch in chunks if re.search(
                rule["source_pattern"], str(ch.get("text", "")), re.I)][:2])
    by_id = {ch.get("id"): ch for ch in chunks}
    for ch in priority[:4]:
        adjacent = by_id.get(ch.get("id", 0) + 1)
        if adjacent:
            priority.append(adjacent)
    ordered = []
    for ch in priority + selected:
        if ch.get("id") not in {item.get("id") for item in ordered}:
            ordered.append(ch)
    ordered = ordered[:10]
    return "\n\n".join(quote_context(ch, 1700) for ch in ordered), ordered


def known_identity_answer(base):
    """Optional trusted answers; regex hits alone do not prove entailment."""
    facts = evidence_for_identity(base)
    parts = []
    for index, rule in enumerate(SETTINGS["identity_rules"]):
        hits = facts[str(index)]
        if hits:
            parts.append(f"{rule['answer']} [Book chunk {hits[0].get('id', '?')}]")
    if not parts:
        return None
    return "Configured observations (require owner validation):\n\n" + "\n\n".join(parts)


def is_identity_question(question):
    return any(_matches_question(rule, question) for rule in SETTINGS["identity_rules"])
