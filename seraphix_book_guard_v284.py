"""Read-only, conservative guard for Seraphix book answers. Standard library only."""
import re
from seraphix_config import SETTINGS

LEAK = [
 r'\b(?:hmm|okay|alright),?\s+(?:the user|let me|we need)\b',
 r'\b(?:the user|user) (?:is asking|asks|wants|requested)\b',
 r'\b(?:let me|i need to|we need to|i should|we should) (?:carefully )?(?:review|think|extract|analy[sz]e|craft|formulate|look through|check)\b',
 r'\blooking through (?:the |these )?chunks\b',
 r'\bthe key points i can extract\b',
 r'\b(?:in|looking at) book chunk \d+\b.*\b(?:i see|there is)\b',
 r'\b(?:i|we) (?:must|should|need to) cite\b',
 r'\b(?:the|our) (?:system|developer) (?:prompt|instruction)\b',
 r'\b(?:final answer|answer) (?:should|must) (?:be|include)\b',
 r'\b(?:we are given|the question asks|from the above)\b',
]
UNSUPPORTED = [(re.compile(pattern, re.I | re.S), "Configured unsupported claim")
               for pattern in SETTINGS["unsupported_patterns"]]

def inspect(answer, valid_ids):
    """Return (ok, reasons); fail closed rather than leaking an answer."""
    if not answer or len(answer.strip()) < 35:
        return False, ['empty or too short']
    reasons=[]
    for pat in LEAK:
        if re.search(pat, answer, re.I|re.S):
            reasons.append('internal reasoning detected')
            break
    for pat, _ in UNSUPPORTED:
        if pat.search(answer):
            reasons.append('unsupported identity or event claim')
            break
    cited = [str(x) for x in re.findall(r'\[Book chunk\s+(\d+)\]', answer, re.I)]
    if not cited:
        reasons.append('no manuscript citations')
    if any(i not in valid_ids for i in cited):
        reasons.append('citation outside retrieved evidence')
    # Reject a response that ends in an unfinished clause.
    if re.search(r'(?:\b(?:her|his|their|the|and|but|because|which|that|to)\s*|[,;:]\s*)$',answer.strip(),re.I):
        reasons.append('truncated sentence')
    return not reasons, reasons


def fallback(question, chunks):
    """Source quotations only; no model-invented biography. Up to 4 excerpts."""
    lines=['I found these manuscript passages, but could not verify a complete generated answer. Here is the source evidence instead:']
    for ch in chunks[:4]:
        content=re.sub(r'\s+',' ',str(ch.get('text',''))).strip()
        if not content:continue
        # Present explicitly as a quotation, never as a verified inference.
        lines.append(f'• [Book chunk {ch.get("id", "?")}] “{content[:340].rstrip()}…”')
    lines.append('These are excerpts, not a complete interpretation. Ask a narrower question for a more precise answer.')
    return '\n\n'.join(lines)


def make_messages(question, excerpts, retry=False):
    system = (
        'You are a cautious manuscript evidence assistant. Only assert facts explicitly supported by supplied excerpts. '
        'Do not infer identity, relationships, or completed events from proximity or speculation. '
        'Do not reverse actor, victim, and witness. '
        'Each factual paragraph must end with one or more [Book chunk N] citations from supplied excerpts. '
        'If evidence is insufficient, say so. Answer in 2-4 short paragraphs. '
        'No thinking, planning, analysis, or meta-commentary. /no_think')
    if retry:
        system += ' IMPORTANT: Your previous attempt failed a private output check. Produce ONLY polished final prose with exact chunk citations. No draft, no commentary.'
    return [ {'role':'system','content':system}, {'role':'user','content':f'QUESTION:\n{question}\n\nMANUSCRIPT EVIDENCE:\n{excerpts}\n\nAnswer the question directly. /no_think'} ]
