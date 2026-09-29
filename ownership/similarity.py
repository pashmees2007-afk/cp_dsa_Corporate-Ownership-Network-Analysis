"""Phase 3 - Levenshtein edit distance and similarity.

Hand-implemented (the plan's "core matching logic remains custom"). Standard
dynamic programme over a (len(a)+1) x (len(b)+1) table, keeping only two rows,
so time is O(len(a) * len(b)) and extra space O(min(len(a), len(b))).
"""


def levenshtein(a, b, limit=None):
    """Minimum number of single-character insertions, deletions and
    substitutions turning a into b.

    With `limit`, stops early and returns limit + 1 as soon as the distance is
    certain to exceed limit (every cell in a row is already above it).
    """
    if len(a) < len(b):
        a, b = b, a                      # b is the shorter: rows have len(b) + 1 cells
    if limit is not None and len(a) - len(b) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1,                  # delete ca
                           cur[j - 1] + 1,               # insert cb
                           prev[j - 1] + (ca != cb)))    # substitute (free if equal)
        if limit is not None and min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def similarity(a, b):
    """1 - distance / length of the longer string; 1.0 for two empty strings."""
    longest = max(len(a), len(b))
    return 1.0 if longest == 0 else 1.0 - levenshtein(a, b) / longest
