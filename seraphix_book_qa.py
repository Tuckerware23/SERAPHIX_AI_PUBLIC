"""Read-only, local manuscript retrieval for Seraphix v2.8.2."""
import json
import math
import re
from collections import Counter
from pathlib import Path

INDEX_REL = Path('Memory') / 'Book_Index' / 'chunks.json'
STOP = set('the a an and or but of in on to for from with is are was were be been it its this that these those i you your me my we they he she his her their what who how why does do did tell explain about  book manuscript character chapter story please seraphix'.split())


def terms(value):
    return [w for w in re.findall(r"[a-z0-9']+", value.lower()) if len(w) > 2 and w not in STOP]


def retrieve(question, base, limit=4):
    path = Path(base) / INDEX_REL
    if not path.is_file():
        raise FileNotFoundError(f'Manuscript index missing: {path}. Run seraphix_book_reader.py first.')
    data = json.loads(path.read_text(encoding='utf-8'))
    chunks = data.get('chunks', [])
    if not isinstance(chunks, list) or not chunks:
        raise ValueError('Manuscript index has no chunks.')
    query = Counter(terms(question))
    if not query:
        return []
    corpus = [Counter(terms(str(chunk.get('text', '')))) for chunk in chunks]
    df = Counter()
    for words in corpus:
        df.update(words.keys())
    scored = []
    for item, words in zip(chunks, corpus):
        score = sum((1 + math.log(words[t])) * math.log(1 + (len(chunks) + 1) / (df[t] + 1)) * min(n, 2)
                    for t, n in query.items() if words[t])
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def book_context(question, base):
    found = retrieve(question, base)
    if not found:
        return None
    excerpts = []
    for chunk in found:
        marker = chunk.get('start', {})
        location = f"paragraph {marker.get('paragraph', '?')}" if 'paragraph' in marker else f"table {marker.get('table', '?')}, row {marker.get('row', '?')}"
        excerpts.append(f"[Book chunk {chunk.get('id', '?')}; begins at {location}]\n{str(chunk.get('text', ''))[:2800]}")
    return '\n\n'.join(excerpts)
