"""Seraphix v3.1.6 — inspectable, slot-based manuscript answer composition.

Evidence is untrusted data. Validation is heuristic, not a proof of entailment.
Logs contain diagnostic codes and counts only, never manuscript/model text.
"""
import json
import logging
import re
from collections import Counter
from collections.abc import Mapping

PARA = re.compile(r'\(P(\d+)\)\s*')
CITE = re.compile(r'\[P(\d+)\]', re.I)
THINK = re.compile(r'<think\b[^>]*>.*?</think\s*>', re.I | re.S)
LEAK = re.compile(r'(?im)^\s*(?:hmm\b|let me (?:think|trace|analy[sz]e)|the user (?:asks|is asking)|(?:my|the) (?:reasoning|analysis)\b)')
VERSION = '3.1.6'
# Only these model-provided reason codes may reach logs or repair prompts.
VERIFIER_REASONS = frozenset({
    'missing_addressee', 'wrong_recipient', 'ambiguous_recipient',
    'missing_context_citation', 'unsupported_detail', 'unsupported_identity',
    'event_order', 'insufficient_evidence', 'rejected',
})
STOP = set('that this with from they their then when what which were have into after before about also said says told there where while would could should because these those them just very some such more only does each over under nearly being again'.split())


class EvidenceValidationError(ValueError):
    """Contains only a diagnostic code, never evidence text."""


def _anchor_id(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]+', value):
        try:
            return int(value)
        except ValueError:
            pass
    raise EvidenceValidationError('invalid_anchor')


def paragraphs(evidence):
    """Validate and merge one source without changing numeric citation IDs.

    Multiple records require the same explicit, nonempty source_id. Callers
    must assign IDs for a single paragraph-number namespace (including chapter
    identity if numbering restarts); chapter display labels alone are not IDs.
    Identical repeated paragraphs are allowed; conflicting text is rejected.
    """
    if not isinstance(evidence, (list, tuple)):
        raise EvidenceValidationError('invalid_evidence_container')
    result = {}
    identities = []
    for e in evidence:
        if not isinstance(e, Mapping):
            raise EvidenceValidationError('invalid_evidence_record')
        anchor = _anchor_id(e.get('anchor'))
        identity = e.get('source_id')
        if identity is not None and (not isinstance(identity, str) or not identity.strip()):
            raise EvidenceValidationError('invalid_source_identity')
        identities.append(identity)
        if 'chapter' in e and not isinstance(e['chapter'], str):
            raise EvidenceValidationError('invalid_evidence_record')
        local = {}
        for field in ('before', 'anchor_text', 'after'):
            source = e.get(field, '')
            if not isinstance(source, str):
                raise EvidenceValidationError('invalid_paragraph_content')
            if not source.strip():
                continue
            parts = PARA.split(source)
            if parts[0].strip() or len(parts) == 1:
                raise EvidenceValidationError('invalid_paragraph_content')
            for i in range(1, len(parts)-1, 2):
                text = parts[i+1].strip()
                if not text:
                    raise EvidenceValidationError('invalid_paragraph_content')
                paragraph_id = _anchor_id(parts[i])
                if paragraph_id in result and result[paragraph_id] != text:
                    raise EvidenceValidationError('conflicting_paragraph_text')
                result[paragraph_id] = local[paragraph_id] = text
        if anchor not in local:
            raise EvidenceValidationError('missing_anchor_paragraph')
    if len(identities) > 1 and (None in identities or len(set(identities)) != 1):
        raise EvidenceValidationError('ambiguous_source_identity')
    return result


def _content(reply):
    msg = getattr(reply, 'message', None)
    if isinstance(msg, dict):
        return str(msg.get('content') or ''), bool(msg.get('thinking'))
    return str(getattr(msg, 'content', '') or ''), bool(getattr(msg, 'thinking', None))


def _clean(raw):
    s = THINK.sub('', raw or '')
    s = re.sub(r'<think\b[^>]*>.*$', '', s, flags=re.I | re.S).strip()
    if s.startswith('```'):
        s = re.sub(r'^```(?:json)?\s*', '', s, flags=re.I)
        s = re.sub(r'\s*```$', '', s)
    return s.strip()


def _extractive(e, ps):
    anchor = int(e['anchor'])
    lines = [f'Here is the evidence surrounding the question in {e.get("chapter", "the manuscript")}:']
    for label, ids in (('Before', [i for i in sorted(ps) if anchor-4 <= i < anchor]),
                       ('Central passage', [anchor]),
                       ('After', [i for i in sorted(ps) if anchor < i <= anchor+3])):
        snippets = []
        for i in ids:
            if i in ps:
                t = re.sub(r'\s+', ' ', ps[i]).strip()
                if len(t) > 440:
                    t = t[:437].rsplit(' ', 1)[0] + '…'
                snippets.append(f'{t} [P{i}]')
        if snippets:
            lines.append(label + ': ' + ' '.join(snippets))
    lines.append('These are source excerpts; a reliable interpretation was not generated.')
    return '\n\n'.join(lines)


def _ids(value):
    if isinstance(value, int) and not isinstance(value, bool):
        return [value]
    if isinstance(value, str):
        return [int(x) for x in re.findall(r'\bP?(\d+)\b', value, re.I)]
    if isinstance(value, list):
        ids = []
        for item in value:
            if type(item) is int:
                ids.append(item)
            elif isinstance(item, str) and re.fullmatch(r'\s*\[?P?\d+\]?\s*', item, re.I):
                ids.extend(_ids(item))
        return ids
    return []


def _terms(s):
    return set(re.findall(r'\b[a-z]{4,}\b', s.lower())) - STOP


def _context_ids(ps, anchor):
    """Use the retriever's bounded window consistently in every assessment."""
    return [i for i in sorted(ps) if anchor - 19 <= i <= anchor + 17]


def _claim_valid(key, claim, ps, anchor):
    if isinstance(claim, str):
        return None, 'missing_fields'
    if not isinstance(claim, dict):
        return None, 'invalid_schema'
    txt = next((claim[k] for k in ('text', 'claim', 'summary', 'answer') if isinstance(claim.get(k), str)), None)
    ref = next((claim[k] for k in ('paragraphs', 'paragraph_ids', 'citations', 'refs', 'citation', 'evidence') if k in claim), None)
    if not txt or not 10 <= len(txt.strip()) <= 600:
        return None, 'invalid_text'
    ids = list(dict.fromkeys(_ids(ref)))
    if not ids:
        return None, 'missing_citations'
    if len(ids) > 6 or any(i not in ps for i in ids):
        return None, 'invalid_citations'
    if key == 'answer' and anchor is not None and anchor not in ids:
        return None, 'missing_anchor_citation'
    if LEAK.search(txt) or '<think' in txt.lower():
        return None, 'reasoning_leak'
    # This is only a lexical plausibility gate; citations do not establish entailment.
    wanted = _terms(txt)
    source = _terms(' '.join(ps[i] for i in ids))
    shared = wanted & source
    if wanted and len(shared) < 2 and len(shared)/len(wanted) < 0.25:
        return None, 'low_lexical_support'
    return (txt.strip(), ids), 'accepted'


def _slot_from_ids(ids, anchor):
    """Only map a repair claim when its citations lie strictly on one side."""
    if ids and all(i < anchor for i in ids):
        return 'before'
    if ids and all(i > anchor for i in ids):
        return 'after'
    return 'answer' if anchor in ids else None


def _parse_claims(raw, ps, anchor=None, requested=None, question=""):
    s = _clean(raw)
    try:
        obj = json.loads(s)
    except (ValueError, TypeError):
        return {}, {'invalid_json': 1}, 'none'
    if not isinstance(obj, dict):
        return {}, {'invalid_schema': 1}, 'none'
    if 'claims' in obj and isinstance(obj['claims'], dict):
        obj = obj['claims']
    if 'recipient' in obj and 'answer' not in obj:
        obj['answer'] = obj['recipient']
    if requested in ('answer', 'before', 'after') and not any(k in obj for k in ('answer','before','after')):
        if any(k in obj for k in ('text','claim','summary')):
            obj = {requested: obj}
    accepted, reasons = {}, Counter()
    mapping = "none"
    for key in ('answer','before','after'):
        if key not in obj:
            reasons['missing_' + key] += 1
            continue
        claim, status = _claim_valid(key, obj[key], ps, None if requested in ('before', 'after') and key == 'answer' else anchor)
        if claim:
            actual_key = key
            if requested in ('before', 'after') and anchor is not None:
                side = _slot_from_ids(claim[1], anchor)
                if key == 'answer' and side == requested:
                    actual_key = requested
                    mapping = 'citation_side_' + requested
                elif key == requested and side != requested:
                    reasons['wrong_temporal_citations'] += 1
                    continue
                elif key == 'answer' and side != 'answer':
                    reasons['wrong_slot_citations'] += 1
                    continue
            accepted[actual_key] = claim
        else:
            reasons[status] += 1
    return accepted, dict(reasons), mapping


def _missing_slots(claims, anchor):
    missing = []
    if 'answer' not in claims or anchor not in claims['answer'][1]:
        missing.append('recipient')
    if 'before' not in claims:
        missing.append('before')
    if 'after' not in claims:
        missing.append('after')
    return missing


def _compose(claims, ps, anchor):
    if _missing_slots(claims, anchor):
        return None
    lines = []
    for key, label in (('answer','Answer'),('before','Before'),('after','After')):
        txt, ids = claims[key]
        txt = txt.rstrip().rstrip('.')
        lines.append(f'{label}: {txt}. ' + ' '.join(f'[P{i}]' for i in ids))
    result = '\n\n'.join(lines)
    if LEAK.search(result) or anchor not in _ids(CITE.findall(result)):
        return None
    return result


def _source_quote_present(quote, sources):
    """Verify a verifier's quoted evidence really appears in supplied source."""
    norm = lambda t: re.sub(r'\s+', ' ', str(t)).strip().casefold()
    q = norm(quote)
    return len(q) >= 14 and any(q in norm(t) for t in sources)


def _verify_claim(key, claim, ps, anchor, question, model, client, log):
    """Conservative evidence-quote verification; never equate citation with truth."""
    txt, ids = claim
    if key == 'before' and any(i >= anchor for i in ids):
        return False, 'temporal_boundary'
    if key == 'after' and any(i <= anchor for i in ids):
        return False, 'temporal_boundary'
    if key == 'answer' and anchor not in ids:
        return False, 'missing_anchor'
    # The cited paragraphs are the proof set. Neighbors provide dialogue context,
    # but must not substitute for a missing citation to the relevant event.
    nearby = set(_context_ids(ps, anchor))
    context_ids = sorted(set(ids) | nearby)
    excerpts = '\n'.join(f'(P{i}) {ps[i]}' for i in context_ids)
    cited = '\n'.join(f'(P{i}) {ps[i]}' for i in ids)
    prompt = (f'QUESTION: {question}\nSLOT: {key}\nANCHOR: P{anchor}\n'
              f'CITED SOURCE PASSAGES:\n{cited}\nADDITIONAL CONTEXT (not citations):\n{excerpts}\n'
              f'CANDIDATE: {txt}\n'
              'Check ALL factual assertions, including each named person, dialogue addressee, '
              'cause, visual detail, and event ordering. If a sentence adds any unsupported '
              'detail, mark false. A valid citation number is not proof. '
              'If the question asks who is addressed, distinguish the speaker, listener, '
              'and other people present. You may be singular or plural; establish the '
              'listener or listeners from evidence. Do not assume everyone present is addressed. '
              'Use a reason code from: ' + ', '.join(sorted(VERIFIER_REASONS)) + '. '
              'Return only JSON {"supported":true/false,"reason":"short_code",'
              '"evidence_quotes":["literal short passage quoted verbatim from CITED SOURCE PASSAGES"]}. '
              'If supported is true, provide at least one literal evidence quote (14+ characters) '
              'from the cited passages. If uncertain, return false. /no_think')
    try:
        reply = client.chat(model=model, messages=[
            {'role': 'system', 'content': 'Strict source-grounded verifier. Return JSON only. /no_think'},
            {'role': 'user', 'content': prompt}], think=False, format='json',
            options={'temperature': 0, 'num_predict': 260, 'num_ctx': 8192})
        raw, _ = _content(reply)
        try:
            obj = json.loads(_clean(raw))
        except (ValueError, TypeError):
            reason = 'invalid_verifier_json'
        else:
            if not isinstance(obj, dict) or type(obj.get('supported')) is not bool:
                reason = 'invalid_verifier_schema'
            elif not obj['supported']:
                code = obj.get('reason')
                reason = 'verifier_' + (code if isinstance(code, str) and code in VERIFIER_REASONS else 'rejected')
            else:
                quotes = obj.get('evidence_quotes')
                if not isinstance(quotes, list) or not quotes or not all(isinstance(q, str) for q in quotes):
                    reason = 'missing_evidence_quote'
                elif not all(_source_quote_present(q, [ps[i] for i in ids]) for q in quotes):
                    reason = 'evidence_quote_not_in_citation'
                else:
                    reason = 'verified'
        ok = reason == 'verified'
        log.info('scene_verify_v314 slot=%s result=%s reason=%s', key, 'pass' if ok else 'fail', reason)
        return ok, reason
    except Exception as exc:
        log.warning('scene_verify_v314 slot=%s result=error type=%s', key, type(exc).__name__)
        return False, 'verification_unavailable'


def _resolve_participant(question, ps, anchor, model, client, log):
    """Resolve dialogue separately; require a literal supporting quotation.

    A verified quotation is necessary but not sufficient for entailment; the model
    must also assert that the quote establishes the recipient. No names hardcoded.
    """
    if not re.search(r'\b(?:who|whom|address(?:es|ed)?|recipient|listener)\b', question, re.I):
        return None
    context_ids = _context_ids(ps, anchor)
    source = '\n'.join(f'(P{i}) {ps[i]}' for i in context_ids)
    prompt = (f'QUESTION: {question}\nDIALOGUE ANCHOR: P{anchor}\nSOURCE:\n{source}\n'
              'Identify who speaks the dialogue at the anchor and the intended '
              'listener or listeners if supported. You may be singular or plural. Distinguish nearby bystanders. '
              'If uncertain, return null for recipient. Output ONLY JSON with '
              '{"speaker":"name or null","recipient":"name or null",'
              '"paragraphs":[numbers],"evidence_quote":"literal excerpt from one cited paragraph"}. '
              'The quote must substantiate the recipient, not merely mention their name. /no_think')
    try:
        reply = client.chat(model=model, messages=[
            {'role':'system','content':'Resolve manuscript dialogue using only source evidence. JSON only. /no_think'},
            {'role':'user','content':prompt}], think=False, format='json',
            options={'temperature':0,'num_predict':240,'num_ctx':8192})
        raw, _ = _content(reply)
        obj = json.loads(_clean(raw))
        if not isinstance(obj, dict):
            raise ValueError('invalid_schema')
        recipient = obj.get('recipient')
        ids = list(dict.fromkeys(_ids(obj.get('paragraphs'))))
        quote = obj.get('evidence_quote')
        if (not isinstance(recipient, str) or not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,70}", recipient.strip())
                or not ids or any(i not in context_ids for i in ids)
                or not isinstance(quote, str) or not _source_quote_present(quote, [ps[i] for i in ids])):
            log.info('scene_participant_v314 status=unresolved reason=invalid_evidence')
            return None
        # A name mentioned in a quote is not enough; require it in the context and
        # leave semantic attribution to the later independent verifier.
        if not any(re.search(r'\b' + re.escape(recipient.strip()) + r'\b', ps[i], re.I) for i in context_ids):
            log.info('scene_participant_v314 status=unresolved reason=unknown_name')
            return None
        log.info('scene_participant_v314 status=candidate cited=%s', len(ids))
        return {'recipient':recipient.strip(), 'ids':ids, 'quote':quote}
    except Exception as exc:
        log.warning('scene_participant_v314 status=unresolved type=%s', type(exc).__name__)
        return None



def _contextual_recipient(participant, question, ps, anchor, model, client, log):
    """Independent contextual assessment; preliminary candidates cannot veto it."""
    if not re.search(r'\b(?:who|whom|address(?:es|ed)?|recipient|listener)\b', question, re.I):
        return None
    neighbors = _context_ids(ps, anchor)
    before = [i for i in neighbors if i < anchor]
    if not before or anchor not in ps:
        return None
    source = '\n'.join(f'(P{i}) {ps[i]}' for i in neighbors)
    prompt = (f'QUESTION: {question}\nTARGET DIALOGUE: P{anchor}\nSOURCE:\n{source}\n'
              'Independently determine who is addressed in the target dialogue. '
              'Do not rely on a candidate supplied by another model call. '
              'Separate speaker, listener and other people mentioned. '
              'You may be singular or plural; include all supported listeners only. '
              'Return JSON only: {"recipient":"name or null",'
              '"confidence":"explicit|contextual|unresolved",'
              '"evidence":[{"paragraph":123,"quote":"exact source excerpt"}]}. '
              'Use explicit only if the target dialogue explicitly names the listener; '
              'use contextual if inferred from adjacent narration. If ambiguous, unresolved. '
              'Quote one passage identifying the person in prior narration and one '
              'passage containing the target dialogue. /no_think')
    try:
        reply = client.chat(model=model, messages=[
            {'role':'system','content':'Independent dialogue attribution audit. Source-grounded JSON only. /no_think'},
            {'role':'user','content':prompt}], think=False, format='json',
            options={'temperature':0,'num_predict':320,'num_ctx':8192})
        raw, _ = _content(reply)
        obj = json.loads(_clean(raw))
        name = obj.get('recipient') if isinstance(obj, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z' -]{1,70}", name.strip()):
            log.info('scene_context_v314 status=unresolved reason=invalid_recipient')
            return None
        name = name.strip()
        confidence = obj.get('confidence')
        if confidence not in ('explicit', 'contextual'):
            log.info('scene_context_v314 status=unresolved reason=confidence_missing')
            return None
        ev = obj.get('evidence')
        if not isinstance(ev, list) or not 2 <= len(ev) <= 5:
            return None
        used = set()
        named_context = False
        for item in ev:
            if not isinstance(item, dict) or type(item.get('paragraph')) is not int:
                return None
            i = item['paragraph']
            if i not in neighbors or not isinstance(item.get('quote'), str) or not _source_quote_present(item['quote'], [ps[i]]):
                log.info('scene_context_v314 status=unresolved reason=bad_quote')
                return None
            used.add(i)
            # Each named listener must occur in the actual quoted context.
            names = re.split(r'\s+and\s+', name, flags=re.I)
            if i < anchor and all(re.search(r'\b' + re.escape(n) + r'\b', item['quote'], re.I) for n in names):
                named_context = True
        if anchor not in used or not named_context:
            log.info('scene_context_v314 status=unresolved reason=missing_dialogue_context')
            return None
        # No explicit addressee is established merely by an assessor label.
        # Contextual inference is always disclosed as such to the user.
        log.info('scene_context_v314 status=contextual cited=%s', len(used))
        return {'recipient':name, 'ids':sorted(used), 'confidence':'contextual'}
    except Exception as exc:
        log.warning('scene_context_v314 status=unresolved type=%s', type(exc).__name__)
        return None


def _contextual_partial(claims, participant, e, ps, anchor, missing):
    lines = []
    if participant:
        ids = participant['ids']
        lines.append('Recipient (contextually supported, not explicitly named in the dialogue): '
                     + participant['recipient'] + '. ' + ' '.join(f'[P{i}]' for i in ids))
    for key, label in (('answer','Answer'),('before','Before'),('after','After')):
        if key in claims and not (key == 'answer' and participant):
            txt, ids = claims[key]
            lines.append(f'{label} (verified by model review): {txt.rstrip().rstrip(".")}. ' +
                         ' '.join(f'[P{i}]' for i in ids))
    outstanding = [x for x in missing if x != 'recipient' or not participant]
    if outstanding:
        lines.append('Not established: ' + ', '.join(outstanding) + '.')
    if not lines:
        return _safe_partial(e, ps, set(missing))
    lines.append('Contextual attribution is an inference; model-assisted verification can still make mistakes.')
    return '\n\n'.join(lines)


def _partial_verified(claims, e, ps, anchor, missing):
    lines = []
    for key, label in (('answer','Answer'),('before','Before'),('after','After')):
        if key in claims:
            txt, ids = claims[key]
            lines.append(f'{label} (verified by model review): {txt.rstrip().rstrip(".")}. ' +
                         ' '.join(f'[P{i}]' for i in ids))
    if not lines:
        return _safe_partial(e, ps, set(missing))
    lines.append('Not established: ' + ', '.join(missing) + '.')
    lines.append('Verification is model-assisted and may still make mistakes.')
    return '\n\n'.join(lines)


def _safe_partial(e, ps, failed):
    # Do not surface unverified model claims as facts.
    prefix = 'A complete verified interpretation is not available.'
    if failed:
        prefix += ' Verification did not pass for: ' + ', '.join(sorted(failed)) + '.'
    return prefix + '\n\n' + _extractive(e, ps)


def answer_question(question, evidence, model, ollama_client, logger=None):
    log = logger or logging.getLogger('seraphix.scene')
    try:
        ps = paragraphs(evidence)
    except EvidenceValidationError as exc:
        code = str(exc)
        log.warning('scene_input_v316 reason=%s', code)
        return 'Scene evidence validation failed: ' + code + '.'
    if not evidence:
        return 'No scene evidence was found.'
    if not ps:
        return 'No readable source paragraphs were found.'
    e = evidence[0]
    anchor = _anchor_id(e['anchor'])
    ps = {i: ps[i] for i in _context_ids(ps, anchor)}
    if anchor not in ps:
        return _extractive(e, ps)
    ids = _context_ids(ps, anchor)
    source = '\n'.join(f'(P{i}) {ps[i]}' for i in ids)
    system = ('Extract concise, factual manuscript claims. Respond with a JSON object only, no reasoning. '
              'Keys: answer, before, after. Each key is an object with "text" (one or two sentences) '
              'and "paragraphs" (array of numeric paragraph IDs). Do not invent identities, events, or citations. '
              'The "answer" must address the question directly and include the anchor ID. '
              'You may be singular or plural; determine the intended listener or listeners from source context; '
              'do not list everyone present as recipients. /no_think')
    tasks = [
        ('all', 'Return answer, before, after objects. If asked who is addressed, identify the supported listener or listeners. Cite the context establishing attribution AND the dialogue paragraph. Do not invent visual details.'),
        ('answer', 'Return an answer object addressing the question. For dialogue attribution, identify supported listeners and cite the context establishing attribution AND the anchor dialogue paragraph.'),
        ('before', 'Return a before object about events strictly earlier than the anchor, with only earlier paragraph citations.'),
        ('after', 'Return an after object about events strictly later than the anchor, with only later paragraph citations. Note scene cuts if supported.'),
    ]
    participant = _resolve_participant(question, ps, anchor, model, ollama_client, log)
    merged = {}
    failures = {}
    for attempt, (slot, instruction) in enumerate(tasks, 1):
        missing = _missing_slots(merged, anchor)
        if not missing:
            break
        if slot != 'all' and ('recipient' if slot == 'answer' else slot) not in missing:
            continue
        participant_hint = (f'\nDIALOGUE PARTICIPANT CANDIDATE (verify, do not assume): {participant["recipient"]}; context citations {participant["ids"]}.\n' if participant else '')
        feedback = '\nREPAIR FEEDBACK (codes only): ' + json.dumps(failures, sort_keys=True) + '\n' if failures else ''
        user = (f'QUESTION: {question}\nANCHOR: P{anchor}\nSOURCE:\n{source}\n'
                f'INSTRUCTION: {instruction} ' + participant_hint + feedback +
                'Return ONLY JSON using the requested key, e.g. {"before":{"text":"...","paragraphs":[123]}} '
                'or with the requested slot key. Use only IDs appearing in SOURCE. /no_think')
        try:
            reply = ollama_client.chat(model=model,
                messages=[{'role':'system','content':system}, {'role':'user','content':user}],
                think=False, format='json', options={'temperature':0,'num_predict':550,'num_ctx':8192})
            raw, thinking = _content(reply)
            parsed, reasons, mapping = _parse_claims(raw, ps, anchor, requested=slot, question=question)
            if not parsed:
                failures[slot] = ','.join(sorted(reasons)) or 'no_claims'
            for key, claim in parsed.items():
                if key not in merged:
                    ok, why = _verify_claim(key, claim, ps, anchor, question, model, ollama_client, log)
                    if ok:
                        merged[key] = claim
                        failures.pop(key, None)
                    else:
                        failures[key] = why
            log.info('scene_slot_v314 attempt=%s requested_slot=%s returned_keys=%s slot_mapping_result=%s parsed=%s rejects=%s chars=%s separate_thinking=%s missing=%s',
                     attempt, slot, ','.join(re.findall(r'\"(answer|before|after|recipient)\"\s*:', _clean(raw))) or 'unknown', mapping, ','.join(parsed) or 'none',
                     ','.join(f'{k}:{v}' for k,v in sorted(reasons.items())) or 'none',
                     len(raw), thinking, ','.join(_missing_slots(merged,anchor)) or 'none')
        except Exception as exc:
            failures[slot] = 'generation_unavailable'
            log.warning('scene_slot_v314_error slot=%s type=%s', slot, type(exc).__name__)
    result = _compose(merged, ps, anchor)
    if result:
        log.info('scene_composed_v314 anchor=P%s', anchor)
        return result
    missing = _missing_slots(merged, anchor)
    log.warning('scene_composition_incomplete_v314 anchor=P%s missing=%s', anchor, ','.join(missing) or 'final_validation')
    contextual = None
    if 'recipient' in missing:
        contextual = _contextual_recipient(participant, question, ps, anchor, model, ollama_client, log)
    return _contextual_partial(merged, contextual, e, ps, anchor, missing)
