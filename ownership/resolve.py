"""Phase 3 - entity resolution.

Maps every observed name variant (holder or held) to a canonical entity ID.

    from ownership.ingest import read_records
    from ownership.resolve import build_index
    index = build_index(read_records("data/ownership_relations.csv").records)
    index.entity_of("M M MURUGAPPAN, Trustee of M M Muthiah Family Trust").name
        -> "M M Muthiah Family Trust"

Command line (writes data/entity_index.csv and data/resolution_report.json):

    python -m ownership.resolve

Pipeline, per name:
  1. holding_entity(): read capacity phrases to find the entity that actually
     holds the shares. "X, Trustee of Y Trust", "X (... on behalf of Y Trust)"
     and "X - As Karta of Y HUF" are holdings of Y, not of the person X.
     Annotations that describe the holder rather than name it ("(Through
     Multiple Schemes)", "(M M Murugappan & ... hold shares on behalf of
     Trust)") are removed.
  2. match_key(): the Phase 2 normalised form, plus a few matching-only rules
     (honorifics, trailing company-form words, "Fly" = "Family").
Then, over the distinct keys of each entity type:
  3. CIN: where a CIN is present it decides. Same CIN -> same entity;
     different CINs -> never merged, whatever the names say.
  4. Exact: equal keys are one entity.
  5. Truncation: a key cut off mid-word (BSE caps names at 50 characters) is
     merged with the only longer key it is a prefix of.
  6. Fuzzy: keys sharing their first 3 characters are found with a trie
     prefix query (blocking), then verified token by token (token_match).
Merges are recorded in a union-find (disjoint-set) structure.

Names of different entity types (corporate / individual) are never merged.
"""
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .normalise import LEGAL_SUFFIXES, tokens
from .similarity import similarity
from .trie import Trie

# ---------------------------------------------------------------- 1. capacity

@dataclass(frozen=True)
class Holding:
    name: str            # text naming the entity that holds the shares
    kind: str | None     # "trust" | "huf" | "firm" when a capacity phrase decided it
    rule: str            # which rule produced it (see holding_entity)


_WS = re.compile(r"\s+")
_PAREN = re.compile(r"\(([^()]*)(?:\)|$)")          # also an unclosed "(... to end of name"
_ANNOTATION = re.compile(
    r"\b(holds?|holding|held|behalf|kar(?:ta|tha)|trustees?|capacity|partners?|through multiple|"
    r"various|aop|formerly|converted|legal heir|alongwith|rep)\b", re.I)
# the same words glued to their neighbours ("...MeyyammaiareTrustees)"); long enough to be safe as substrings
_ANNOTATION_GLUED = re.compile(r"trustee|behalf|capacity|karta|kartha", re.I)
_DASH_TAIL = re.compile(r"\s*-\s+(.*)$")
_DASH_TAIL_KEYWORD = re.compile(r"\b(holds?|behalf|trustees?|kar(?:ta|tha))\b", re.I)
_BEHALF = re.compile(r"\bbehalf\s+of\s+(?:the\s+)?(firm\s+)?([^()]+?)\s*\)?\s*\.?$", re.I)
_PARTNER = re.compile(r"\bcapacity\s+of\s+partner\s+of\s+(.+?)(?:\s*-\s*firm)?\s*\)?\s*$", re.I)
_TRUSTEE_OF = re.compile(r"\btrustee\s+of\s+(.+)$", re.I)
_KARTA_OF = re.compile(r"\bkar(?:ta|tha)\s+of\s+(.+?\bhuf)\b", re.I)
_HUF_NAME = re.compile(r"^(.+?\bhuf)\b", re.I)
_KARTA_OF_HUF = re.compile(r"\bkar(?:ta|tha)\b.*\bhuf\b", re.I)
_INITIALS_SKIP = {"and", "of", "the"}


def _is_acronym(inner, before):
    """True if the bracketed text is the initials of the words before it: "... Fund(IEPF)"."""
    letters = re.sub(r"[^a-z]", "", inner.lower())
    words = [w for w in re.findall(r"[a-z]+", before.lower()) if w not in _INITIALS_SKIP]
    return len(letters) >= 2 and "".join(w[0] for w in words[-len(letters):]) == letters


def strip_annotations(name):
    """Remove bracketed notes and "- ... holds shares ..." tails that describe
    the holder rather than name it. Brackets that are part of a name, like
    "(India)" or "(Mauritius)", are kept."""
    def drop(m):
        inner = m.group(1)
        if _ANNOTATION.search(inner) or _ANNOTATION_GLUED.search(inner) or _is_acronym(inner, name[:m.start()]):
            return " "
        return m.group(0)

    s = _PAREN.sub(drop, name)
    tail = _DASH_TAIL.search(s)
    if tail and _DASH_TAIL_KEYWORD.search(tail.group(1)):
        s = s[:tail.start()]
    return _WS.sub(" ", s).strip(" ,.-")


def _named(text):
    """A specific entity name, not just "Trust" / "the Firm"."""
    return len(tokens(text)) >= 2


def holding_entity(raw):
    """The entity that holds the shares a filed name refers to. Rules, in order:

      behalf_of       "... on behalf of <Name> Trust|HUF" or "... on behalf of the firm <Name>"
      partner_of      "... in the capacity of Partner of <Firm>"
      trustee_of      "X, Trustee of <Trust>"
      karta_of        "X - As Karta of <Name> HUF"
      huf             "<Name> HUF" followed by anything (karta, "rep. by", ...)
      karta_capacity  "X (in the capacity of Karta of HUF)"  ->  "X HUF"
      as_filed        none of the above: the name itself, annotations removed
    """
    s = _WS.sub(" ", raw).strip()

    m = _BEHALF.search(s)
    if m and _named(m.group(2)):
        target = strip_annotations(m.group(2))
        last = tokens(target)[-1] if tokens(target) else ""
        if m.group(1) or last in ("trust", "huf"):
            kind = "trust" if last == "trust" else "huf" if last == "huf" else "firm"
            return Holding(target, kind, "behalf_of")

    m = _PARTNER.search(s)
    if m and _named(m.group(1)):
        return Holding(strip_annotations(m.group(1)), "firm", "partner_of")

    # before strip_annotations, which would cut a " - As Karta of ..." tail
    m = _KARTA_OF.search(s)
    if m and _named(m.group(1)):
        return Holding(strip_annotations(m.group(1)), "huf", "karta_of")

    clean = strip_annotations(s)

    m = _TRUSTEE_OF.search(clean)
    if m and _named(m.group(1)):
        return Holding(strip_annotations(m.group(1)), "trust", "trustee_of")

    m = _HUF_NAME.search(clean)
    if m:
        return Holding(m.group(1).strip(), "huf", "huf")

    if _KARTA_OF_HUF.search(s):
        return Holding(clean + " HUF", "huf", "karta_capacity")

    return Holding(clean, None, "as_filed")


def holding_type(filed_type, holding):
    """Entity type after capacity parsing: an HUF is typed individual (as in
    Phase 1, category A1(a)); a trust or firm is not a natural person."""
    if holding.kind == "huf":
        return "individual"
    if holding.kind in ("trust", "firm"):
        return "corporate"
    return filed_type


# ---------------------------------------------------------------- 2. match key

HONORIFICS = frozenset({"mr", "mrs", "ms", "smt", "shri", "sri", "dr"})
ABBREVIATIONS = {"fly": "family"}
# Trailing words that name a legal form, dropped for matching only.
FORM_WORDS = LEGAL_SUFFIXES | {"company", "co", "corporation", "corp", "inc", "plc",
                               "pte", "bv", "lp", "llc", "ac"}


def match_key(name):
    toks = [ABBREVIATIONS.get(t, t) for t in tokens(name)]
    while len(toks) > 1 and toks[0] in HONORIFICS:
        toks = toks[1:]
    while len(toks) > 1 and toks[-1] in FORM_WORDS:
        toks = toks[:-1]
    return " ".join(toks)


# ---------------------------------------------------------------- 6. verification

TOKEN_THRESHOLD = 0.8        # minimum per-token similarity for a differing token
BLOCK_PREFIX = 3             # fuzzy step compares only keys sharing this many leading characters
CANDIDATE_RADIUS = 0.2       # lookup(): near-match radius, as a fraction of query length
KEY_THRESHOLD = 0.8          # whole-key similarity, used only when token_guard=False


def token_match(a, b, threshold=TOKEN_THRESHOLD):
    """Are keys a and b spellings of one name?

    - Equal once spaces are removed ("chocka lingam" / "chockalingam"): yes.
    - Otherwise the keys must have the same number of tokens, and position by
      position each pair of tokens must be equal, or be a spelling variant:
      both longer than 3 characters, no digits, similarity >= threshold.
    - At most half the tokens may differ.

    Short tokens (initials, "mid", "aif") and numbers must match exactly: that
    is what separates "M V Muthiah" from "M M Muthiah" and "Nifty 100" from
    "Nifty 50", which whole-string similarity scores as near-identical.
    """
    if a == b or a.replace(" ", "") == b.replace(" ", ""):
        return True
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False
    diffs = 0
    for x, y in zip(ta, tb):
        if x == y:
            continue
        diffs += 1
        if min(len(x), len(y)) <= 3 or any(c.isdigit() for c in x + y):
            return False
        if similarity(x, y) < threshold:
            return False
    return 2 * diffs <= len(ta)


# ---------------------------------------------------------------- union-find

class DisjointSet:
    """Union-find with path halving and union by size, over any hashable items.
    Each set may carry CINs; two sets with different CINs cannot be joined."""

    def __init__(self):
        self.parent, self.size, self.cins = {}, {}, {}

    def add(self, x, cin=None):
        if x not in self.parent:
            self.parent[x], self.size[x], self.cins[x] = x, 1, set()
        if cin:
            self.cins[self.find(x)].add(cin)

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        """Join the sets of a and b. False if already joined or CINs conflict."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.cins[ra] and self.cins[rb] and self.cins[ra] != self.cins[rb]:
            return False
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        self.cins[ra] |= self.cins.pop(rb)
        return True


# ---------------------------------------------------------------- index

@dataclass(eq=False)
class Entity:
    id: str
    name: str                    # canonical display name
    entity_type: str
    variants: list = field(default_factory=list)     # raw names, most frequent first
    keys: list = field(default_factory=list)         # match keys
    cin: str | None = None
    listed: bool = False         # appears as a held (BSE-listed) company


@dataclass
class _Obs:                      # everything seen for one raw name
    raw: str
    filed_type: str
    holding: Holding
    entity_type: str
    key: str
    count: int = 0
    listed: bool = False
    cin: str | None = None


class EntityIndex:
    def __init__(self):
        self.entities = []           # sorted by id
        self._by_raw = {}            # (raw name, filed type) -> Entity
        self._by_key = {}            # (match key, entity type) -> Entity
        self._tries = {}             # entity type -> Trie over match keys
        self.merges = []             # (reason, key_a, key_b, entity type)
        self.stats = {}
        self._observations = []

    # ---- queries

    def entity_of(self, raw_name, entity_type=None):
        """Entity for a name exactly as filed. entity_type (the filed type)
        is needed only if the same text was filed under both types."""
        if entity_type is not None:
            return self._by_raw[(raw_name, entity_type)]
        hits = {self._by_raw[(raw_name, t)] for t in ("corporate", "individual")
                if (raw_name, t) in self._by_raw}
        if not hits:
            raise KeyError(raw_name)
        if len(hits) > 1:
            raise KeyError(f"{raw_name!r} is filed under both types; pass entity_type")
        return hits.pop()

    def lookup(self, query, limit=5):
        """Entities for a free-text query: exact key match first, then keys
        starting with the query, then near matches. For the Phase 7 search box."""
        key = match_key(holding_entity(query).name) or match_key(query)
        found, seen = [], set()

        def add(entity):
            if entity.id not in seen:
                seen.add(entity.id)
                found.append(entity)

        tries = [self._tries[t] for t in sorted(self._tries)]
        for trie in tries:
            if key in trie:
                add(trie.get(key))
        for trie in tries:
            for _, ent in trie.with_prefix(key):
                add(ent)
        radius = max(1, int(len(key) * CANDIDATE_RADIUS))
        near = []
        for trie in tries:
            near.extend(trie.within(key, radius))
        for _, ent, _ in sorted(near, key=lambda t: t[2]):
            add(ent)
        return found[:limit]

    def __len__(self):
        return len(self.entities)


def _observations(records):
    obs = {}

    def see(raw, filed_type, cin, listed):
        o = obs.get((raw, filed_type))
        if o is None:
            h = holding_entity(raw)
            etype = holding_type(filed_type, h)
            o = obs[(raw, filed_type)] = _Obs(raw, filed_type, h, etype, match_key(h.name))
        o.count += 1
        o.listed |= listed
        o.cin = o.cin or cin

    for r in records:
        see(r.holder_name, r.entity_type, r.holder_cin, False)
        see(r.held_name, "corporate", r.held_cin, True)
    return list(obs.values())


def build_index(records, *, capacity=True, truncation=True, fuzzy=True, token_guard=True,
                token_threshold=TOKEN_THRESHOLD, key_threshold=KEY_THRESHOLD):
    """Resolve the names in `records` (OwnershipRecords). The keyword switches
    exist for the ablation in ownership.er_eval; the defaults are the full method."""
    observations = _observations(records)
    if not capacity:                 # ablation: Phase 2 normalisation only
        for o in observations:
            o.holding = Holding(o.raw, None, "as_filed")
            o.entity_type, o.key = o.filed_type, match_key(o.raw)

    index = EntityIndex()
    ds = DisjointSet()
    nodes = defaultdict(list)        # (key, type) -> observations
    for o in observations:
        node = (o.key, o.entity_type)
        nodes[node].append(o)
        ds.add(node, o.cin)

    # 3. CIN: same CIN (and type) -> one entity; conflicting CINs are refused by the DisjointSet
    by_cin = defaultdict(list)
    for o in observations:
        if o.cin:
            by_cin[(o.cin, o.entity_type)].append((o.key, o.entity_type))
    for members in by_cin.values():
        for other in members[1:]:
            if ds.union(members[0], other):
                index.merges.append(("cin", members[0][0], other[0], other[1]))

    # tries per entity type over the distinct keys (4. exact matching is the node itself)
    tries = defaultdict(Trie)
    for key, etype in nodes:
        tries[etype].insert(key)
    comparisons = 0

    for etype, trie in sorted(tries.items()):
        keys = sorted(k for k, t in nodes if t == etype)

        # 5. truncation: a mid-word cut with exactly one longer completion
        if truncation:
            for key in keys:
                if len(key) < 15:
                    continue
                longer = [k for k, _ in trie.with_prefix(key) if k != key]
                if len(longer) == 1 and longer[0][len(key)] != " ":
                    if ds.union((key, etype), (longer[0], etype)):
                        index.merges.append(("truncation", key, longer[0], etype))

        # 6. fuzzy: prefix blocking through the trie, then verification
        if fuzzy:
            for key in keys:
                for cand, _ in trie.with_prefix(key[:BLOCK_PREFIX]):
                    if cand <= key:                  # each unordered pair once
                        continue
                    comparisons += 1
                    ok = token_match(key, cand, token_threshold) if token_guard \
                        else similarity(key, cand) >= key_threshold
                    if ok and ds.union((key, etype), (cand, etype)):
                        index.merges.append(("fuzzy", key, cand, etype))

    # entities: one per disjoint set
    groups = defaultdict(list)
    for node in nodes:
        groups[ds.find(node)].append(node)
    entities = []
    for members in groups.values():
        obs = sorted((o for n in members for o in nodes[n]), key=lambda o: (-o.count, o.raw))
        listed = [o for o in obs if o.listed]
        if listed:                   # a listed company keeps its BSE name
            name = listed[0].raw
        else:                        # the holding name behind the most rows
            weight = Counter()
            for o in obs:
                weight[o.holding.name] += o.count
            name = min(weight, key=lambda n: (-weight[n], -n.count(" "), n))
        cins = {o.cin for o in obs if o.cin}
        entities.append(Entity(
            id="", name=name, entity_type=obs[0].entity_type,
            variants=[o.raw for o in obs], keys=sorted({n[0] for n in members}),
            cin=min(cins) if cins else None, listed=bool(listed)))
    entities.sort(key=lambda e: (e.name.casefold(), e.entity_type, e.variants[0]))
    width = len(str(len(entities)))
    for i, e in enumerate(entities, 1):
        e.id = f"E{i:0{width + 1}d}"

    for e in entities:
        for k in e.keys:
            index._by_key[(k, e.entity_type)] = e
    for o in observations:
        index._by_raw[(o.raw, o.filed_type)] = index._by_key[(o.key, o.entity_type)]
    for etype, trie in tries.items():
        for key, _ in trie.with_prefix(""):
            trie.insert(key, index._by_key[(key, etype)])
    index._tries = dict(tries)
    index.entities = entities
    index._observations = observations

    per_type = Counter(t for _, t in nodes)
    index.stats = {
        "name_variants": len(observations),
        "distinct_match_keys": len(nodes),
        "entities": len(entities),
        "entities_by_type": dict(Counter(e.entity_type for e in entities)),
        "listed_entities": sum(e.listed for e in entities),
        "capacity_rules": dict(Counter(o.holding.rule for o in observations)),
        "merges": dict(Counter(m[0] for m in index.merges)),
        "fuzzy_comparisons": {"prefix_blocking": comparisons,
                              "all_pairs": sum(n * (n - 1) // 2 for n in per_type.values())},
    }
    return index


# ---------------------------------------------------------------- output

def write_outputs(index, root):
    rows = []
    for o in index._observations:
        e = index._by_raw[(o.raw, o.filed_type)]
        rows.append({"name_variant": o.raw, "filed_type": o.filed_type, "entity_id": e.id,
                     "canonical_name": e.name, "entity_type": e.entity_type,
                     "match_key": o.key, "capacity_rule": o.holding.rule, "rows": o.count})
    rows.sort(key=lambda r: (r["entity_id"], -r["rows"], r["name_variant"]))
    with open(root / "data" / "entity_index.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    report = dict(index.stats)
    report["merged_pairs"] = [{"reason": r, "entity_type": t, "a": a, "b": b}
                              for r, a, b, t in index.merges if r != "cin"]
    report["multi_variant_entities"] = sum(len(e.variants) > 1 for e in index.entities)
    (root / "data" / "resolution_report.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    return report


def main():
    from .ingest import read_records
    root = Path(__file__).resolve().parent.parent
    index = build_index(read_records(root / "data" / "ownership_relations.csv").records)
    report = write_outputs(index, root)
    print(json.dumps({k: v for k, v in report.items() if k != "merged_pairs"}, indent=2))


if __name__ == "__main__":
    main()
