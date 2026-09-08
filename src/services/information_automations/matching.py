"""Bounded literal matching. Article text is data, never executable instructions."""
import unicodedata


def normalize(value: str) -> str:
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def keyword_match(text: str, conditions: dict) -> bool:
    text = normalize(text)
    all_words, any_words, excluded = (conditions.get(key, []) for key in ('all', 'any', 'exclude'))
    return (all(normalize(word) in text for word in all_words)
            and (not any_words or any(normalize(word) in text for word in any_words))
            and not any(normalize(word) in text for word in excluded))
