import unittest
from telegram_assistant.relevance import relevance, terms


class RelevanceTests(unittest.TestCase):
    def test_requires_all_words_and_ignores_accents(self):
        self.assertGreater(relevance({'text': 'Automatización industrial'}, ['automatizacion industrial'])[0], 0)
        self.assertEqual(relevance({'text': 'Redes sociales'}, ['redes de datos'])[0], 0)
        self.assertEqual(terms('de la y'), [])

    def test_filenames_and_explicit_alternatives(self):
        message = {'text': '', 'file': {'name': 'Computer Networks.pdf'}}
        self.assertEqual(relevance(message, ['redes de datos'])[0], 0)
        self.assertGreater(relevance(message, ['redes de datos', 'computer networks'])[0], 0)
        self.assertGreater(relevance({'file': {'name': 'Computer_Networks.pdf'}}, ['computer networks'])[0], 0)
        self.assertEqual(relevance({'text': 'redesdatos'}, ['datos'])[0], 0)
