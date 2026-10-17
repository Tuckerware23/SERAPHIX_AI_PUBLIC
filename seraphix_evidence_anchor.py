"""Seraphix v3.1.5: deterministic local BM25 scene retrieval.

No model calls, logging, or index writes. Candidate metadata contains no passages.
Ambiguous or invalid chapter requests return a status string and no evidence.
"""
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from seraphix_manuscript_library import INDEX

VERSION = '3.1.5'
CHAPTER = re.compile(r"\bchapters?\s+([a-z0-9]+)\b", re.I)
QUOTES = re.compile(r'''"([^"\n]{8,150})"|\u201c([^\u201d\n]{8,150})\u201d|(?<!\w)'([^'\n]{8,150})'(?!\w)''')
STOP = frozenset("""the a an and or but of in on to for from with is are was were
be been being it its this that these those i you your me my we they he she his
her their what who whom how why does do did tell explain about book manuscript
character chapter story please when where which said says say asked asks question
would could should have has had then than as at by not""".split())
K1 = 1.2
B = 0.75
SCENE_RADIUS = 2
SCENE_WEIGHT = 0.35
AMBIGUITY_MARGIN = 0.05


def _words(value):
    """Same conservative normalization for questions and manuscript text."""
    value = unicodedata.normalize('NFKC', value).casefold().replace('\u2019', "'")
    result = []
    for word in re.findall(r"[^\W_]+(?:'[^\W_]+)?", value, re.UNICODE):
        word = re.sub(r"'s$", '', word)
        if word in STOP or len(word) < 2:
            continue
        if len(word) > 4 and word.endswith('ies'):
            word = word[:-3] + 'y'
        elif len(word) > 4 and word.endswith('s') and not word.endswith(('ss', 'ous', 'is', 'us')):
            word = word[:-1]
        inflected = False
        if len(word) > 6 and word.endswith('ing'):
            word = word[:-3]
            inflected = True
        elif len(word) > 5 and word.endswith('ed'):
            word = word[:-2]
            inflected = True
        if inflected and len(word) > 3 and word[-1:] == word[-2:-1] and word[-1:] in 'bdgmntpr':
            word = word[:-1]
        result.append(word)
    return result


def _chapter_number(value):
    if value.isdigit():
        number = int(value)
        return number if number > 0 else None
    value = value.upper()
    if not value or not re.fullmatch(r'M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})', value):
        return None
    numbers = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    return sum(-numbers[c] if i + 1 < len(value) and numbers[c] < numbers[value[i+1]] else numbers[c]
               for i, c in enumerate(value))


def _chapter_key(label):
    match = CHAPTER.search(label)
    number = _chapter_number(match.group(1)) if match else None
    return ('number', number) if number is not None else ('label', label.strip().casefold())


def _query(question):
    matches = list(CHAPTER.finditer(question))
    numbers = [_chapter_number(match.group(1)) for match in matches]
    if re.search(r'\bchapters?\s+[+-]\d|\bchapters?\s+\d+\.\d', question, re.I):
        return [], None, 'invalid_chapter_constraint'
    # A multi-chapter API is deliberately not inferred from one endpoint.
    has_range = any(re.match(r'\s*(?:,|and\b|or\b|through\b|to\b|[-\u2013])\s*(?:chapter\s+)?(?:\d+|[ivxlcdm]+)\b',
                             question[match.end():], re.I) for match in matches)
    if matches and (None in numbers or len(set(numbers)) != 1 or has_range):
        return [], None, 'invalid_chapter_constraint'
    return _words(CHAPTER.sub('', question)), numbers[0] if numbers else None, None


class _BM25:
    def __init__(self, documents):
        self.average_length = sum(map(len, documents)) / max(len(documents), 1) or 1
        df = Counter()
        for tokens in documents:
            df.update(set(tokens))
        self.idf = {word: math.log(1 + (len(documents) - count + 0.5) / (count + 0.5))
                    for word, count in df.items()}

    def score(self, query, tokens, paragraph_count=1):
        freq = Counter(tokens)
        length_ratio = len(tokens) / (self.average_length * paragraph_count)
        return sum(self.idf.get(word, 0) * freq[word] * (K1 + 1) /
                   (freq[word] + K1 * (1 - B + B * length_ratio))
                   for word in sorted(set(query)) if freq[word])


def _bounds(ps, index, before, after):
    key = _chapter_key(ps[index]['chapter'])
    start, end = index, index + 1
    while start > 0 and index - start < before and _chapter_key(ps[start-1]['chapter']) == key:
        start -= 1
    while end < len(ps) and end - index - 1 < after and _chapter_key(ps[end]['chapter']) == key:
        end += 1
    return start, end


def rank_candidates(question, paragraphs, limit=5):
    """Return deduplicated scene rankings and status, without source passages.

    Rank by combined paragraph/context BM25 and phrase evidence, breaking ties
    by phrase support, rarity coverage, query coverage, then paragraph BM25.
    Position stabilizes otherwise identical results; close competing scenes are
    marked ambiguous instead of silently selected.
    """
    query, chapter, error = _query(question)
    if error:
        return {'status': error, 'candidates': []}
    eligible = [i for i, p in enumerate(paragraphs)
                if chapter is None or _chapter_key(p['chapter']) == ('number', chapter)]
    if chapter is not None and not eligible:
        return {'status': 'chapter_not_found', 'candidates': []}
    if not query or not eligible:
        return {'status': 'no_match', 'candidates': []}
    documents = [_words(p['text']) for p in paragraphs]
    bm25 = _BM25(documents)
    query_set = set(query)
    pairs = set(zip(query, query[1:]))
    quotes = [_words(next(part for part in match if part)) for match in QUOTES.findall(question)]
    candidates = []
    for index in eligible:
        tokens = documents[index]
        anchor_score = bm25.score(query, tokens)
        if anchor_score <= 0:
            continue
        start, end = _bounds(paragraphs, index, SCENE_RADIUS, SCENE_RADIUS)
        context = [word for doc in documents[start:end] for word in doc]
        scene_score = bm25.score(query, context, end - start)
        matched = query_set & set(tokens)
        rarity = sum(bm25.idf[word] for word in sorted(matched))
        matched_pairs = pairs & set(zip(tokens, tokens[1:]))
        phrase_score = 0.15 * sum(bm25.idf.get(a, 0) + bm25.idf.get(b, 0)
                                  for a, b in sorted(matched_pairs))
        for quote in quotes:
            if quote and any(tokens[i:i+len(quote)] == quote for i in range(len(tokens)-len(quote)+1)):
                phrase_score += sum(bm25.idf.get(word, 0) for word in quote)
        candidates.append({'anchor': paragraphs[index]['id'], 'chapter': paragraphs[index]['chapter'],
            'score': anchor_score + SCENE_WEIGHT * scene_score + phrase_score,
            'anchor_score': anchor_score, 'scene_score': scene_score,
            'phrase_score': phrase_score, 'rarity_coverage': rarity,
            'term_coverage': len(matched) / len(query_set),
            'scene_first': paragraphs[start]['id'], 'scene_last': paragraphs[end-1]['id'],
            '_index': index, '_start': start, '_end': end})
    candidates.sort(key=lambda c: (-c['score'], -c['phrase_score'], -c['rarity_coverage'],
                                   -c['term_coverage'], -c['anchor_score'], c['_index']))
    chosen = []
    for candidate in candidates:
        # Greedy non-maximum suppression of heavily overlapping scene windows.
        if any(max(0, min(candidate['_end'], old['_end']) - max(candidate['_start'], old['_start'])) /
               min(candidate['_end'] - candidate['_start'], old['_end'] - old['_start']) >= 0.5
               for old in chosen):
            continue
        chosen.append(candidate)
    status = 'no_match' if not chosen else 'ok'
    if len(chosen) > 1 and (chosen[0]['score'] - chosen[1]['score']) / chosen[0]['score'] <= AMBIGUITY_MARGIN:
        status = 'ambiguous'
    public = [{k: v for k, v in c.items() if not k.startswith('_')} for c in chosen[:max(0, limit)]]
    return {'status': status, 'candidates': public}


def retrieve_anchored(question, base, before=19, after=17):
    path = Path(base) / INDEX
    if not path.exists():
        return None, []
    ps = json.loads(path.read_text(encoding='utf-8')).get('paragraphs', [])
    if not ps:
        return '', []
    ranked = rank_candidates(question, ps)
    status = ranked['status']
    if status != 'ok':
        messages = {'ambiguous': 'Ambiguous manuscript scenes: add a chapter or a more distinctive phrase.',
                    'invalid_chapter_constraint': 'Invalid or multiple chapter constraints; specify one chapter.',
                    'chapter_not_found': 'The requested chapter was not found.'}
        return messages.get(status, ''), []
    selected = ranked['candidates'][0]
    anchor_i = next(i for i, p in enumerate(ps) if p['id'] == selected['anchor'])
    anchor = ps[anchor_i]
    start, end = _bounds(ps, anchor_i, max(0, before), max(0, after))
    def lines(seq):
        return '\n'.join(f"(P{p['id']}) {p['text']}" for p in seq)
    evidence = [{'id': 1, 'chapter': anchor['chapter'], 'anchor': anchor['id'],
                 'first': ps[start]['id'], 'last': ps[end-1]['id'],
                 'before': lines(ps[start:anchor_i]), 'anchor_text': lines([anchor]),
                 'after': lines(ps[anchor_i+1:end])}]
    e = evidence[0]
    text = (f"[Evidence 1; {e['chapter']}; anchor P{e['anchor']}; context P{e['first']}-P{e['last']}]\n"
            f"BEFORE ANCHOR (earlier narrative paragraphs):\n{e['before']}\n"
            f"ANCHOR (the paragraph to explain):\n{e['anchor_text']}\n"
            f"AFTER ANCHOR (later narrative paragraphs):\n{e['after']}")
    return text, evidence


def fallback(evidence):
    e = evidence[0]
    before = e['before'].splitlines()[-3:]
    after = e['after'].splitlines()[:3]
    return ('I found the exact evidence location, but could not verify a complete interpretation. '
            f"The anchor is P{e['anchor']} in {e['chapter']}.\n\n"
            + '\n'.join(before + [e['anchor_text']] + after))
