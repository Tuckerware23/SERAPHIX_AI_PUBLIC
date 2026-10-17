"""Offline v3.1.6 regressions; all passages and model replies are synthetic."""
import io
import json
import logging
import unittest
from types import SimpleNamespace

import seraphix_scene_answer as scene


PS = {5: 'Alex waited beside the sealed doorway.',
      8: 'Blair watched the empty hallway quietly.',
      9: 'Mira turned toward Alex beside the doorway.',
      10: 'Mira warned, "You must leave the doorway now."',
      11: 'Alex departed through the doorway immediately.',
      14: 'The hallway remained silent until morning.'}
QUESTION = 'Who does Mira warn?'
CLAIMS = {
    'answer': {'text': 'Mira warned Alex to leave the doorway.', 'paragraphs': [9, 10]},
    'before': {'text': PS[9], 'paragraphs': [9]},
    'after': {'text': PS[11], 'paragraphs': [11]}}


def evidence():
    return [{'anchor': 10, 'chapter': 'Synthetic chapter',
             'before': '\n'.join(f'(P{i}) {t}' for i, t in PS.items() if i < 10),
             'anchor_text': '(P10) ' + PS[10],
             'after': '\n'.join(f'(P{i}) {t}' for i, t in PS.items() if i > 10)}]


def supported(quote):
    return {'supported': True, 'evidence_quotes': [quote]}


class Client:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.replies)
        return SimpleNamespace(message={'content': value if isinstance(value, str) else json.dumps(value)})


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.log = logging.Logger('offline', logging.INFO)
        self.log.addHandler(logging.StreamHandler(self.stream))

    def answer(self, client):
        return scene.answer_question(QUESTION, evidence(), 'offline-mock', client, self.log)

    def assert_input_failure(self, records, code):
        client = Client([])
        result = scene.answer_question(QUESTION, records, 'offline-mock', client, self.log)
        self.assertEqual(result, 'Scene evidence validation failed: ' + code + '.')
        self.assertEqual(client.calls, [])
        self.assertIn('reason=' + code, self.stream.getvalue())
        self.assertNotIn(PS[10], self.stream.getvalue())

    def test_single_source_numeric_string_anchor_and_tuple(self):
        record = evidence()[0]
        record['anchor'] = '10'
        self.assertEqual(scene.paragraphs((record,)), PS)
        client = Client([{'recipient': None}, CLAIMS,
                         supported(PS[9]), supported(PS[9]), supported(PS[11])])
        result = scene.answer_question(QUESTION, (record,), 'offline-mock', client, self.log)
        self.assertIn('Answer:', result)
        self.assertEqual(len(client.calls), 5)

    def test_same_source_duplicate_paragraphs_are_idempotent(self):
        records = [dict(evidence()[0], source_id='synthetic-source') for _ in range(2)]
        self.assertEqual(scene.paragraphs(records), PS)
        client = Client([{'recipient': None}, CLAIMS,
                         supported(PS[9]), supported(PS[9]), supported(PS[11])])
        result = scene.answer_question(QUESTION, records, 'offline-mock', client, self.log)
        self.assertIn('Before:', result)
        self.assertIn('After:', result)
        self.assertEqual(len(client.calls), 5)

    def test_conflicting_duplicate_text_never_reaches_client(self):
        records = [dict(evidence()[0], source_id='synthetic-source') for _ in range(2)]
        records[1]['anchor_text'] = '(P10) A different synthetic event occurred.'
        self.assert_input_failure(records, 'conflicting_paragraph_text')

    def test_conflicts_within_one_record_are_rejected(self):
        record = evidence()[0]
        record['after'] += '\n(P10) A different synthetic event occurred.'
        self.assert_input_failure([record], 'conflicting_paragraph_text')

    def test_multiple_records_need_one_explicit_identity(self):
        for identities in [(None, None), ('one', None), ('one', 'two')]:
            with self.subTest(identities=identities):
                records = [dict(evidence()[0], source_id=i) for i in identities]
                self.assert_input_failure(records, 'ambiguous_source_identity')

    def test_distinct_sources_with_disjoint_ids_still_rejected(self):
        self.assert_input_failure([
            {'source_id': 'one', 'anchor': 1, 'anchor_text': '(P1) Synthetic first passage.'},
            {'source_id': 'two', 'anchor': 2, 'anchor_text': '(P2) Synthetic second passage.'},
        ], 'ambiguous_source_identity')

    def test_malformed_containers_and_records(self):
        for value in (None, '', {}, 0, iter([])):
            with self.subTest(type=type(value).__name__):
                self.assert_input_failure(value, 'invalid_evidence_container')
        for value in (None, 'text', [], 10):
            with self.subTest(record=value):
                self.assert_input_failure([value], 'invalid_evidence_record')

    def test_invalid_anchors_and_identity(self):
        for value in (None, True, -1, 10.0, 'P10', ' 10 ', 'x', '9' * 5000):
            with self.subTest(anchor_type=type(value).__name__):
                self.assert_input_failure([dict(evidence()[0], anchor=value)], 'invalid_anchor')
        for value in ('', ' ', 42, []):
            with self.subTest(identity=value):
                self.assert_input_failure([dict(evidence()[0], source_id=value)], 'invalid_source_identity')

    def test_malformed_contents_and_missing_anchor(self):
        for value in (None, 123, [], 'Unlabeled synthetic text.', '(P10)',
                      '(P10) (P11) Synthetic text.', 'preamble (P10) Synthetic text.'):
            with self.subTest(content=value):
                self.assert_input_failure([dict(evidence()[0], anchor_text=value)], 'invalid_paragraph_content')
        self.assert_input_failure([dict(evidence()[0], anchor=99)], 'missing_anchor_paragraph')
        self.assert_input_failure([dict(evidence()[0], chapter=[])], 'invalid_evidence_record')
        self.assert_input_failure([evidence()[0], {'anchor': True}], 'invalid_anchor')

    def test_empty_containers_remain_controlled_without_calls(self):
        for records in ([], ()):
            client = Client([])
            self.assertEqual(scene.answer_question(QUESTION, records, 'mock', client),
                             'No scene evidence was found.')
            self.assertEqual(client.calls, [])

    def test_existing_failure_codes_are_preserved(self):
        parsed, reasons, _ = scene._parse_claims('{}', PS, 10)
        self.assertEqual(parsed, {})
        self.assertEqual(reasons, {'missing_answer': 1, 'missing_before': 1, 'missing_after': 1})
        self.assertEqual(scene._claim_valid('answer',
            dict(CLAIMS['answer'], paragraphs=[999]), PS, 10)[1], 'invalid_citations')
        client = Client([{'supported': False, 'reason': 'insufficient_evidence'}])
        self.assertEqual(scene._verify_claim('answer', (CLAIMS['answer']['text'], [9, 10]),
            PS, 10, QUESTION, 'mock', client, self.log), (False, 'verifier_insufficient_evidence'))

    def test_malformed_parser_contract(self):
        for raw, reason in [('not json', 'invalid_json'), ('[]', 'invalid_schema'),
                            ('null', 'invalid_schema'), ('{"answer":', 'invalid_json')]:
            with self.subTest(raw=raw):
                parsed, reasons, mapping = scene._parse_claims(raw, PS, 10)
                self.assertEqual((parsed, reasons, mapping), ({}, {reason: 1}, 'none'))

    def test_wrong_preliminary_candidate_cannot_veto_verified_answer(self):
        client = Client([{'recipient': 'Blair', 'paragraphs': [8], 'evidence_quote': PS[8]},
                         CLAIMS, supported(PS[9]), supported(PS[9]), supported(PS[11])])
        result = self.answer(client)
        self.assertIn('Answer: Mira warned Alex', result)
        self.assertIn('Before:', result)
        self.assertIn('After:', result)

    def test_plural_you_reaches_semantic_verification(self):
        ps = {9: 'Mira faced Alex and Blair by the doorway.',
              10: 'Mira warned, "You must both leave the doorway now."'}
        raw = json.dumps({'answer': {'text': 'Mira warns Alex and Blair to leave the doorway.',
                                     'paragraphs': [9, 10]}})
        parsed, _, _ = scene._parse_claims(raw, ps, 10, question=QUESTION)
        self.assertIn('answer', parsed)
        client = Client([supported(ps[10])])
        self.assertTrue(scene._verify_claim('answer', parsed['answer'], ps, 10,
                                           QUESTION, 'mock', client, self.log)[0])

    def test_contextual_attribution_uses_same_window(self):
        participant = {'recipient': 'Alex', 'ids': [5], 'quote': PS[5]}
        client = Client([{'recipient': 'Alex', 'confidence': 'contextual', 'evidence': [
            {'paragraph': 5, 'quote': PS[5]}, {'paragraph': 10, 'quote': PS[10]}]}])
        result = scene._contextual_recipient(participant, QUESTION, PS, 10,
                                             'mock', client, self.log)
        self.assertEqual(result['ids'], [5, 10])
        rendered = scene._contextual_partial({}, result, evidence()[0], PS, 10,
                                             ['recipient', 'before', 'after'])
        self.assertIn('contextually supported', rendered)
        self.assertIn('Not established: before, after', rendered)

    def test_contextual_assessor_can_correct_preliminary_candidate(self):
        client = Client([{'recipient': 'Alex', 'confidence': 'contextual', 'evidence': [
            {'paragraph': 9, 'quote': PS[9]}, {'paragraph': 10, 'quote': PS[10]}]}])
        result = scene._contextual_recipient({'recipient': 'Blair'}, QUESTION, PS, 10,
                                             'mock', client, self.log)
        self.assertEqual(result['recipient'], 'Alex')

    def test_contextual_attribution_requires_real_named_context_and_dialogue(self):
        cases = [
            {'recipient': 'Alex', 'confidence': 'unresolved', 'evidence': []},
            {'recipient': 'Alex', 'confidence': 'contextual', 'evidence': [
                {'paragraph': 8, 'quote': PS[8]}, {'paragraph': 10, 'quote': PS[10]}]},
            {'recipient': 'Alex', 'confidence': 'contextual', 'evidence': [
                {'paragraph': 9, 'quote': PS[9]}, {'paragraph': 10, 'quote': 'Invented dialogue quotation.'}]},
            {'recipient': 'Alex', 'confidence': 'contextual', 'evidence': [
                {'paragraph': 5, 'quote': PS[5]}, {'paragraph': 9, 'quote': PS[9]}]},
        ]
        for reply in cases:
            with self.subTest(reply=reply):
                self.assertIsNone(scene._contextual_recipient(None, QUESTION, PS, 10,
                    'mock', Client([reply]), self.log))

    def test_all_assessors_receive_consistent_source_window(self):
        client = Client([{'recipient': 'Alex', 'paragraphs': [5], 'evidence_quote': PS[5]},
                         CLAIMS, supported(PS[9]), supported(PS[9]), supported(PS[11])])
        self.answer(client)
        for call in client.calls:
            prompt = call['messages'][1]['content']
            self.assertIn('(P5)', prompt)
            self.assertIn('(P14)', prompt)

    def test_evidence_quotes_must_be_from_cited_paragraphs(self):
        for reply, reason in [(supported(PS[8]), 'evidence_quote_not_in_citation'),
                              (supported('fabricated quotation here'), 'evidence_quote_not_in_citation'),
                              ({'supported': True}, 'missing_evidence_quote'),
                              ('bad json', 'invalid_verifier_json'),
                              ({'supported': 'true'}, 'invalid_verifier_schema')]:
            with self.subTest(reason=reason):
                client = Client([reply])
                self.assertEqual(scene._verify_claim('answer', (CLAIMS['answer']['text'], [9, 10]),
                    PS, 10, QUESTION, 'mock', client, self.log), (False, reason))

    def test_specific_failure_feedback_and_preserved_sections(self):
        replacement = dict(CLAIMS)
        replacement['before'] = {'text': 'Blair watched the empty hallway quietly.', 'paragraphs': [8]}
        client = Client([{'recipient': None}, CLAIMS,
                         {'supported': False, 'reason': 'missing_addressee'},
                         supported(PS[9]), supported(PS[11]), replacement, supported(PS[9])])
        result = self.answer(client)
        self.assertIn('Before: ' + PS[9], result)
        self.assertNotIn('Before: Blair', result)
        self.assertIn('verifier_missing_addressee', client.calls[-2]['messages'][1]['content'])
        self.assertEqual(len(client.calls), 7)

    def test_verified_answer_survives_failed_other_sections(self):
        client = Client([{'recipient': None}, {'answer': CLAIMS['answer']},
                         supported(PS[9]), 'not json', '[]'])
        result = self.answer(client)
        self.assertIn('Answer (verified by model review): Mira warned Alex', result)
        self.assertIn('Not established: before, after', result)

    def test_malformed_generation_is_repaired_without_losing_sections(self):
        client = Client([{'recipient': None}, 'not json', {'answer': CLAIMS['answer']},
                         supported(PS[9]), {'before': CLAIMS['before']}, supported(PS[9]),
                         {'after': CLAIMS['after']}, supported(PS[11])])
        result = self.answer(client)
        self.assertIn('Answer:', result)
        self.assertIn('Before:', result)
        self.assertIn('After:', result)
        self.assertIn('invalid_json', client.calls[2]['messages'][1]['content'])
        self.assertNotIn('ValueError', self.stream.getvalue())

    def test_plural_attribution_is_not_automatically_accepted(self):
        claim = ('Mira warns Alex and Blair to leave the doorway.', [9, 10])
        client = Client([{'supported': False, 'reason': 'wrong_recipient'}])
        self.assertEqual(scene._verify_claim('answer', claim, PS, 10, QUESTION,
            'mock', client, self.log), (False, 'verifier_wrong_recipient'))

    def test_model_reason_text_never_enters_logs_or_repair_prompts(self):
        secret = 'PRIVATE_SYNTHETIC_TOKEN credential=abc'
        client = Client([{'recipient': None}, CLAIMS,
                         {'supported': False, 'reason': secret},
                         supported(PS[9]), supported(PS[11]), {'answer': CLAIMS['answer']},
                         supported(PS[9])])
        self.answer(client)
        self.assertNotIn('private_synthetic_token', self.stream.getvalue().lower())
        self.assertNotIn(secret, str(client.calls[-2]))
        self.assertIn('verifier_rejected', client.calls[-2]['messages'][1]['content'])


if __name__ == '__main__':
    unittest.main()
