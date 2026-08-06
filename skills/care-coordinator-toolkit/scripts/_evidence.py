#!/usr/bin/env python3
"""Does the snippet actually contain the value it is offered as evidence for?

Imported by `letter_record.py` and `insurance_claim_review.py`. Not a command:
the leading underscore keeps it out of the `SKILL.md` invocation rule, because
there is nothing here for a person to run.

**Why this is one module and not two copies.** Audit finding #14, measured
6 August 2026: `letter_record.py` checked containment and `insurance_claim_review.py`
checked only that a snippet existed and was not blank. A cold agent worked a
household's share out by subtraction, quoted it against *"The balance is payable
by the policyholder"* — a line with no number in it — and was refused by the
first script and accepted by the second, which then reported SGD 0.00
outstanding against a letter saying SGD 360.00. One rule implemented twice is
two answers that eventually disagree, and the weaker one was the one that
produced money.

**What this cannot do.** It cannot verify that a snippet is verbatim. There is
no document text to diff against — only an image a model already looked at. It
catches a value quoted against text stating a different value, which is what
confabulation on a familiar-looking form looks like. It does not catch a
snippet invented whole, and nothing available offline would. The check is weak
on purpose and its weakness is the reason a flagged record still goes to a
person.

No network access. No filesystem access. No state.
"""

import re
from decimal import Decimal, InvalidOperation

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# Words a company name ends with that a letterhead may or may not print.
SUFFIXES = {"ltd", "limited", "pte", "llp", "inc", "plc", "co", "company",
            "holdings", "sg", "singapore"}

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
DIGITS = re.compile(r"\d+")
WORD = re.compile(r"[0-9a-z]+")

MONTH_NUMBER = {}
for _index, _short in enumerate(MONTHS, start=1):
    MONTH_NUMBER[_short.lower()] = _index
MONTH_NUMBER.update({
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "sept": 9, "october": 10,
    "november": 11, "december": 12,
})

VERBATIM_LIMIT = (
    "verbatim cannot be verified here. There is no document text to diff a "
    "snippet against, only an image the model already looked at, so this "
    "checks that the extracted value appears in the text quoted for it. That "
    "catches a number quoted against text saying a different number. It does "
    "not catch a snippet invented whole, and no check available here would"
)


def snippet_has_amount(snippet, amount):
    """True when some figure printed in the snippet equals `amount`.

    Compared as Decimals after grouping separators are stripped, so SGD
    1,220 is evidence for 1220.00 and 482 is not evidence for 4,820.00 —
    a digit sequence that merely appears inside another is not the figure.
    """
    for token in NUMBER.findall(snippet):
        try:
            if Decimal(token.replace(",", "")) == amount:
                return True
        except InvalidOperation:
            continue
    return False


def snippet_has_days(snippet, days):
    """A window in days is a number on the page, read the same way.

    'within a month' is a reading of 30 days, not a quotation of it.
    """
    return snippet_has_amount(snippet, Decimal(days))


def snippet_has_date(snippet, value):
    """True when day, month and year are all present in the snippet.

    The month may be a number or a name, long or short. Order and separators
    are deliberately not checked: a letter prints 01 Jun 2026, 1/6/26 and
    2026-06-01 for the same day, and this has to accept all three while
    refusing a date the page does not carry at all.
    """
    tokens = set(DIGITS.findall(snippet))
    lower = snippet.lower()
    if str(value.year) not in tokens:
        return False
    if str(value.day) not in tokens and f"{value.day:02d}" not in tokens:
        return False
    if str(value.month) in tokens or f"{value.month:02d}" in tokens:
        return True
    return any(name in lower for name, number in MONTH_NUMBER.items()
               if number == value.month)


def snippet_has_issuer(snippet, issuer):
    """Every meaningful word of the name appears somewhere in the letterhead.

    Case and a company suffix are what differ between a name written out in a
    record and the same name printed on a page; the words themselves are not.
    A name with no word characters at all — a Chinese or Tamil one — falls back
    to a substring match, since there is nothing to tokenise.
    """
    wanted = [word for word in WORD.findall(issuer.lower())
              if len(word) >= 3 and word not in SUFFIXES]
    if not wanted:
        return bool(issuer.strip()) and issuer.strip().lower() in snippet.lower()
    present = set(WORD.findall(snippet.lower()))
    return all(word in present for word in wanted)
