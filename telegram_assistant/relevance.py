"""Deterministic lexical relevance; no remote embeddings or invented synonyms."""
import re
import unicodedata

STOPWORDS = set('a al de del el en es la las los lo o para por que un una unos unas y'.split())


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold().replace('_', ' '))
                   if not unicodedata.combining(c))


def terms(text):
    return list(dict.fromkeys(t for t in re.findall(r'\w+', normalize(text))
                             if t not in STOPWORDS))


def relevance(message, queries):
    text = normalize(message.get('text') or '')
    filename = normalize((message.get('file') or {}).get('name') or '')
    words = set(re.findall(r'\w+', text + ' ' + filename))
    best, matched = 0, []
    for query in queries:
        tokens = terms(query)
        if not tokens or not set(tokens) <= words:
            continue
        score = 10 * len(tokens)
        if normalize(query) in text + ' ' + filename:
            score += 15
        score += 8 * sum(t in set(re.findall(r'\w+', filename)) for t in tokens)
        if score > best:
            best, matched = score, tokens
    return best, matched
