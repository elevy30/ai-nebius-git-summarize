"""Task 1: Evaluation rubric definitions and pass/fail logic."""

from enum import Enum


class Rating(str, Enum):
    GOOD = "good"
    OK = "ok"
    BAD = "bad"


# Criterion definitions: explicit thresholds for good / ok / bad
RUBRIC = {
    "fluency": {
        "good": "Natural, easy-to-read sentences that flow well. No awkward phrasing.",
        "ok": "Readable but contains some awkward phrasing or unnatural word choices.",
        "bad": "Hard to read, broken or incomplete sentences, incoherent structure.",
    },
    "grammar": {
        "good": "No spelling or punctuation errors.",
        "ok": "1-2 minor spelling or punctuation errors.",
        "bad": "3 or more errors, or any major grammatical mistake.",
    },
    "tone": {
        "good": "Friendly, credible sales voice. Persuasive without being pushy.",
        "ok": "Mostly appropriate tone but inconsistent — shifts between formal/casual.",
        "bad": "Wrong tone entirely: too formal, robotic, aggressive, or sarcastic.",
    },
    "length": {
        "good": "50-90 words.",
        "ok": "40-49 or 91-110 words.",
        "bad": "Below 40 or above 110 words.",
    },
    "grounding": {
        "good": "Uses only information provided in the product features. No invented claims.",
        "ok": "Mostly grounded but includes minor embellishments or vague generalizations.",
        "bad": "Invents features, specs, or claims not present in the input data.",
    },
    "latency": {
        "good": "Average time per call < 2 seconds.",
        "ok": "Average time per call 2-5 seconds.",
        "bad": "Average time per call > 5 seconds.",
    },
    "cost": {
        "good": "Average cost per call < $0.001.",
        "ok": "Average cost per call $0.001-$0.005.",
        "bad": "Average cost per call > $0.005.",
    },
}

# Criteria that the LLM judge evaluates (excludes programmatic ones)
JUDGE_CRITERIA = ["fluency", "grammar", "tone", "length", "grounding"]

# All criteria
ALL_CRITERIA = list(RUBRIC.keys())


def compute_final_score(ratings: dict[str, str]) -> str:
    """Apply pass bar and go/no-go rules.

    Pass bar: at least 4 'good' ratings and 0 'bad' ratings.
    Go/no-go: if grounding != 'good', auto-fail.

    Args:
        ratings: dict mapping criterion name to 'good'/'ok'/'bad'

    Returns:
        'pass' or 'fail'
    """
    # Go/no-go rule: grounding must be good
    if ratings.get("grounding") != "good":
        return "fail"

    good_count = sum(1 for v in ratings.values() if v == "good")
    bad_count = sum(1 for v in ratings.values() if v == "bad")

    if good_count >= 4 and bad_count == 0:
        return "pass"
    return "fail"


def count_words(text: str) -> int:
    """Count words in text."""
    return len(text.split())


def rate_length(text: str) -> str:
    """Programmatically rate the length criterion."""
    wc = count_words(text)
    if 50 <= wc <= 90:
        return "good"
    elif (40 <= wc <= 49) or (91 <= wc <= 110):
        return "ok"
    else:
        return "bad"
