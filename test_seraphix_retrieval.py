"""Synthetic, offline retrieval regressions. No private manuscript is loaded."""
import json
import tempfile
import unittest
from pathlib import Path

import seraphix_evidence_anchor as retrieval
from seraphix_manuscript_library import INDEX


def paragraph(number, text, chapter='Chapter 4: Synthetic'):
    return {'id': number, 'chapter': chapter, 'text': text}


class RetrievalTests(unittest.TestCase):
    def retrieve(self, question, paragraphs, **kwargs):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / INDEX
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'paragraphs': paragraphs}), encoding='utf-8')
            return retrieval.retrieve_anchored(question, folder, **kwargs)

    def test_rare_event_outweighs_common_question_words(self):
        ps = [paragraph(1, 'Aria said when the engine alarm sounded.'),
              paragraph(2, 'Aria mentioned the crystalline fracture.'),
              paragraph(3, 'Aria said when the engine alarm sounded.'),
              paragraph(4, 'Aria said when the engine alarm sounded.')]
        _, evidence = self.retrieve('What did Aria say when the crystalline fracture occurred?', ps)
        self.assertEqual(evidence[0]['anchor'], 2)

    def test_normalization_apostrophes_possessives_and_inflections(self):
        self.assertEqual(retrieval._words("Pilot’s warnings were contagious."),
                         retrieval._words("pilot's warning was contagious"))
        self.assertEqual(retrieval._words('WHO was she warning when she said this?'), ['warn'])

    def test_nearby_evidence_improves_scene_ranking(self):
        ps = [paragraph(1, 'An engine fracture occurred.', 'Chapter 2'),
              paragraph(2, 'The pilot waited.', 'Chapter 2'),
              paragraph(3, 'The engine fracture occurred.', 'Chapter 3'),
              paragraph(4, 'Aria issued an evacuation warning.', 'Chapter 3')]
        ranked = retrieval.rank_candidates('Aria engine fracture evacuation', ps)
        self.assertEqual(ranked['candidates'][0]['chapter'], 'Chapter 3')

    def test_candidates_are_deduplicated_within_a_scene(self):
        ps = [paragraph(1, 'Aria saw an engine fracture.'),
              paragraph(2, 'Aria warned about the engine fracture.'),
              paragraph(3, 'The engine fracture widened.')]
        ranked = retrieval.rank_candidates('Aria engine fracture', ps)
        self.assertEqual(len(ranked['candidates']), 1)

    def test_numeric_query_matches_roman_heading_and_reverse(self):
        for label, query in [('Chapter IX: Synthetic', 'Chapter 9: crystalline fracture'),
                             ('Chapter 9: Synthetic', 'Chapter IX: crystalline fracture')]:
            with self.subTest(label=label):
                _, evidence = self.retrieve(query, [paragraph(1, 'A crystalline fracture occurred.', label)])
                self.assertEqual(evidence[0]['anchor'], 1)

    def test_missing_or_invalid_chapter_never_broadens(self):
        ps = [paragraph(1, 'A crystalline fracture occurred.', 'Chapter 2')]
        for query in ['Chapter 99: crystalline fracture', 'Chapter IIX: crystalline fracture',
                      'Chapter 2 and Chapter 3: crystalline fracture',
                      'Chapters 2-3: crystalline fracture', 'Chapter -2 crystalline fracture',
                      'Chapter 2.5 crystalline fracture']:
            with self.subTest(query=query):
                status, evidence = self.retrieve(query, ps)
                self.assertEqual(evidence, [])
                self.assertTrue(status)

    def test_equal_evidence_is_explicitly_ambiguous(self):
        ps = [paragraph(1, 'A crystalline fracture occurred.', 'Chapter 2'),
              paragraph(2, 'A crystalline fracture occurred.', 'Chapter 3')]
        ranked = retrieval.rank_candidates('crystalline fracture', ps)
        self.assertEqual(ranked['status'], 'ambiguous')
        self.assertEqual([c['anchor'] for c in ranked['candidates']], [1, 2])
        status, evidence = self.retrieve('crystalline fracture', ps)
        self.assertIn('Ambiguous', status)
        self.assertEqual(evidence, [])

    def test_chapter_boundaries_and_interface_preserved(self):
        ps = [paragraph(1, 'A crystalline fracture occurred.', 'Chapter II'),
              paragraph(2, 'The pilot evacuated.', 'Chapter II'),
              paragraph(3, 'An unrelated event occurred.', 'Chapter III')]
        text, evidence = self.retrieve('Chapter 2 crystalline fracture', ps)
        self.assertIsInstance(text, str)
        self.assertEqual(len(evidence), 1)
        expected = {'id', 'chapter', 'anchor', 'first', 'last', 'before', 'anchor_text', 'after'}
        self.assertEqual(set(evidence[0]), expected)
        self.assertEqual((evidence[0]['first'], evidence[0]['last']), (1, 2))
        self.assertNotIn('(P3)', text)

    def test_repeatable_scores_and_no_text_in_candidate_metadata(self):
        ps = [paragraph(1, 'A crystalline fracture occurred.', 'Chapter 2'),
              paragraph(2, 'The engine hummed.', 'Chapter 3')]
        first = retrieval.rank_candidates('crystalline fracture', ps)
        self.assertEqual(first, retrieval.rank_candidates('crystalline fracture', ps))
        self.assertNotIn('crystalline', json.dumps(first))
        self.assertGreater(first['candidates'][0]['score'], 0)

    def test_bm25_frequency_saturation_and_length_normalization(self):
        scorer = retrieval._BM25([['fracture'], ['engine'] * 20])
        once = scorer.score(['fracture'], ['fracture'])
        twice = scorer.score(['fracture'], ['fracture', 'fracture'])
        verbose = scorer.score(['fracture'], ['fracture'] + ['engine'] * 100)
        self.assertGreater(twice, once)
        self.assertLess(twice, 2 * once)
        self.assertLess(verbose, once)
        self.assertEqual(scorer.score(['fracture', 'fracture'], ['fracture']), once)

    def test_corpus_rarity_outweighs_multiple_common_terms(self):
        ps = [paragraph(1, 'Aria engine alarm hallway pilot.'),
              paragraph(2, 'A crystalline fracture.', 'Chapter 5')]
        ps.extend(paragraph(i, 'Aria engine alarm hallway pilot.', 'Chapter 6') for i in range(3, 30))
        ranked = retrieval.rank_candidates('Aria engine alarm hallway pilot crystalline fracture', ps)
        self.assertEqual(ranked['candidates'][0]['anchor'], 2)

    def test_quote_forms_are_normalized_without_treating_possessive_as_quote(self):
        ps = [paragraph(1, 'The pilot warned about a crystalline fracture.')]
        scores = []
        for query in ['"crystalline fracture"', '\u201ccrystalline fracture\u201d', "'crystalline fracture'"]:
            ranked = retrieval.rank_candidates(query, ps)
            scores.append(ranked['candidates'][0]['score'])
        self.assertEqual(scores, [scores[0]] * 3)
        self.assertEqual(retrieval.QUOTES.findall("The pilot's crystalline fracture"), [])

    def test_near_equal_distinct_scenes_are_ambiguous_even_with_limit_one(self):
        ps = [paragraph(1, 'A crystalline fracture occurred.', 'Chapter 2'),
              paragraph(2, 'A crystalline fracture occurred.', 'Chapter 3')]
        ranked = retrieval.rank_candidates('crystalline fracture', ps, limit=1)
        self.assertEqual(ranked['status'], 'ambiguous')
        self.assertEqual(len(ranked['candidates']), 1)

    def test_empty_missing_and_no_match(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(retrieval.retrieve_anchored('fracture', folder), (None, []))
        self.assertEqual(self.retrieve('fracture', []), ('', []))
        self.assertEqual(self.retrieve('Who was she?', [paragraph(1, 'An engine hummed.')]), ('', []))
        self.assertEqual(self.retrieve('crystalline', [paragraph(1, 'An engine hummed.')]), ('', []))


if __name__ == '__main__':
    unittest.main()
