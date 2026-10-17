"""Seraphix v3.0: chapter-aware, read-only narrative evidence retrieval.
Works with v2.9's existing indexed manuscript. Never edits manuscript sources.
"""
import json, re, math
from collections import Counter
from seraphix_config import SETTINGS
from pathlib import Path
from seraphix_manuscript_library import INDEX, tokenize

CHAPTER_PATTERN = re.compile(r'\bchapter\s+(\d+|[ivxlcdm]+)\b', re.I)
QUOTED = re.compile(r'[“\"]([^”\"]{12,160})[”\"]')


def _chapter_filter(question, paragraphs):
    match=CHAPTER_PATTERN.search(question)
    if not match: return None
    number=match.group(1).lower()
    return {p['chapter'] for p in paragraphs if re.search(r'\bchapter\s+'+re.escape(number)+r'\b',p['chapter'],re.I)}


def _score(p, terms, names, quotes):
    text=p['text'].lower()
    words=Counter(tokenize(text))
    score=sum(1+math.log1p(words[w]) for w in terms if words[w])
    score+=sum(3 for n in names if re.search(r'\b'+re.escape(n)+r'\b',text))
    score+=sum(18 for phrase in quotes if phrase.lower() in text)
    return score


def retrieve_narrative(question, base, max_passages=3):
    path=Path(base)/INDEX
    if not path.is_file():return None,[]
    data=json.loads(path.read_text(encoding='utf-8'))
    ps=data.get('paragraphs',[])
    if not ps:return '',[]
    allowed=_chapter_filter(question,ps)
    if allowed is not None and not allowed:return '',[]
    terms=set(tokenize(CHAPTER_PATTERN.sub('',question)))
    names=[n for n in SETTINGS["entities"] if re.search(r'\b'+n+r'\b',question,re.I)]
    quotes=[x.strip() for x in QUOTED.findall(question)]
    # First identify a relevant anchor paragraph, then expand in both directions.
    ranked=[]
    for i,p in enumerate(ps):
        if allowed is not None and p['chapter'] not in allowed:continue
        score=_score(p,terms,names,quotes)
        # Adjacent paragraphs help recover actions when the anchor is dialogue.
        for k in (i-2,i-1,i+1,i+2):
            if 0<=k<len(ps) and ps[k]['chapter']==p['chapter']:
                score+=0.22*_score(ps[k],terms,names,quotes)
        if score>0:ranked.append((score,i))
    ranked.sort(reverse=True)
    selected=[]
    for score,i in ranked:
        if any(abs(i-j)<26 for j in selected):continue
        selected.append(i)
        if len(selected)>=max_passages:break
    selected.sort()
    evidence=[]
    for j,i in enumerate(selected,1):
        chapter=ps[i]['chapter']
        # Wider context than v2.9; strictly respect chapter boundaries.
        start=max(0,i-14);end=min(len(ps),i+18)
        while start<i and ps[start]['chapter']!=chapter:start+=1
        while end>i+1 and ps[end-1]['chapter']!=chapter:end-=1
        group=ps[start:end]
        lines=[f"(P{p['id']}) {p['text']}" for p in group]
        evidence.append({'id':j,'chapter':chapter,'first':group[0]['id'],'last':group[-1]['id'],
                         'anchor':ps[i]['id'],'text':'\n'.join(lines)})
    snippets=[]
    for e in evidence:
        snippets.append(f"[Passage {e['id']}; {e['chapter']}; paragraphs {e['first']}-{e['last']}; anchor P{e['anchor']}]\n{e['text']}")
    return '\n\n'.join(snippets),evidence


def clean_final(raw):
    """Reject, rather than publish, obvious untagged reasoning or unfinished text."""
    raw=re.sub(r'<think>.*?</think>','',raw or '',flags=re.I|re.S).strip()
    if re.search(r'<think>|(?:^|\n)\s*(?:hmm[,.: ]|let me |i need to |we should |the user (?:asks|is asking)|looking through the chunks|now, the events)',raw,re.I):return None
    if re.search(r'\b(?:let me trace|i can extract|i need to find|the question asks|i should cite)\b',raw,re.I):return None
    if len(raw)<55 or not re.search(r'[.!?][\s\]]*$',raw):return None
    return raw
