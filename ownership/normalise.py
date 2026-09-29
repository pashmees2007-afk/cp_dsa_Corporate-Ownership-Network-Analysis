"""Phase 2 - entity-name normaliser.

    normalise_name("E.I.D.PARRY (INDIA) LTD.")          -> "eid parry india"
    normalise_name("Birla Group Holdings Pvt. Limited")  -> "birla group holdings"

Steps, in order:
  1. Drop "(Formerly ...)" notes. They record an old name, and they often end
     in a legal suffix that would otherwise stop step 6 from reaching the real
     suffix before the note.
  2. Case folding.
  3. "&" becomes "and", so "Large & Mid Cap" and "Large And Mid Cap" agree.
  4. Punctuation stripping. Apostrophes are deleted ("children's" ->
     "childrens"); every other non-alphanumeric character becomes a space.
  5. Runs of two or more single-letter tokens are joined, so initials agree
     however they were typed: "E.I.D.PARRY", "E.I.D. Parry" and "EID Parry"
     all give "eid parry"; "M A M ARUNACHALAM" and "MAM Arunachalam" both
     give "mam arunachalam".
  6. Trailing legal suffixes are removed (repeatedly, so "pvt ltd" goes
     entirely). Only trailing ones: "Private" in "X Private Equity Fund" is
     part of the name. A name made only of suffixes is left as it is.
  7. A leading "the" is removed: filings say "The Tata Power Company Limited"
     where BSE's company name is "Tata Power Company Ltd".

This is canonicalisation, not matching: two different spellings of one entity
("Lakshmi Venkatachalam Fly Trust" / "... Family Trust") still differ after
this step. Grouping those is Phase 3 (entity resolution).
"""
import re

LEGAL_SUFFIXES = frozenset({"ltd", "limited", "pvt", "private", "llp"})

_FORMERLY = re.compile(r"\(\s*formerly\b[^)]*\)?", re.I)   # also an unclosed "(Formerly ..."
_APOSTROPHE = re.compile(r"['’`]")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _join_initials(tokens):
    out, run = [], []
    for tok in tokens:
        if len(tok) == 1:
            run.append(tok)
            continue
        if run:
            out.append("".join(run) if len(run) > 1 else run[0])
            run = []
        out.append(tok)
    if run:
        out.append("".join(run) if len(run) > 1 else run[0])
    return out


def _strip_suffixes(tokens):
    end = len(tokens)
    while end > 0 and tokens[end - 1] in LEGAL_SUFFIXES:
        end -= 1
    return tokens[:end] if end else tokens


def _strip_article(tokens):
    return tokens[1:] if len(tokens) > 1 and tokens[0] == "the" else tokens


def tokens(name):
    """Normalised tokens of an entity name (see module docstring)."""
    s = _FORMERLY.sub(" ", name).casefold().replace("&", " and ")
    s = _NON_ALNUM.sub(" ", _APOSTROPHE.sub("", s))
    return _strip_article(_strip_suffixes(_join_initials(s.split())))


def normalise_name(name):
    """Canonical form of an entity name; "" if nothing alphanumeric is left."""
    return " ".join(tokens(name))
