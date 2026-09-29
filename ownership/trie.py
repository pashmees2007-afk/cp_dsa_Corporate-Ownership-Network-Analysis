"""Phase 3 - character trie over canonical entity names.

Supports the three lookups entity resolution needs:

    exact       get(key)                 O(m)                   m = key length
    prefix      with_prefix(prefix)      O(m + size of output)
    near-match  within(word, k)          every key at Levenshtein distance <= k

`within` walks the trie depth-first carrying one row of the edit-distance
table per node (Hanov's method). Keys sharing a prefix share the rows for that
prefix, and a branch is abandoned as soon as every cell of its row exceeds k,
so most of the trie is never visited. `cells` counts the table cells computed,
which is what makes the saving over pairwise comparison measurable.

The depth-first walks use an explicit stack rather than recursion.
"""


class _Node:
    __slots__ = ("children", "key", "value")

    def __init__(self):
        self.children = {}
        self.key = None          # full key if a key ends here
        self.value = None


class Trie:
    def __init__(self):
        self.root = _Node()
        self.size = 0
        self.cells = 0           # edit-distance cells computed by within(), cumulative

    def __len__(self):
        return self.size

    def __contains__(self, key):
        node = self._find(key)
        return node is not None and node.key is not None

    def insert(self, key, value=None):
        node = self.root
        for ch in key:
            node = node.children.setdefault(ch, _Node())
        if node.key is None:
            self.size += 1
        node.key, node.value = key, value

    def _find(self, prefix):
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return None
        return node

    def get(self, key, default=None):
        node = self._find(key)
        return node.value if node is not None and node.key is not None else default

    def with_prefix(self, prefix):
        """(key, value) for every key starting with prefix, in sorted order."""
        start = self._find(prefix)
        if start is None:
            return []
        out, stack = [], [start]
        while stack:
            node = stack.pop()
            if node.key is not None:
                out.append((node.key, node.value))
            # push in reverse so the smallest character is popped first
            stack.extend(node.children[c] for c in sorted(node.children, reverse=True))
        return out

    def within(self, word, k):
        """[(key, value, distance)] for every key with levenshtein(word, key) <= k."""
        out = []
        first = list(range(len(word) + 1))           # row for the empty prefix
        if self.root.key is not None and first[-1] <= k:
            out.append((self.root.key, self.root.value, first[-1]))
        stack = [(child, ch, first) for ch, child in self.root.children.items()]
        while stack:
            node, ch, prev = stack.pop()
            row = [prev[0] + 1]
            for j in range(1, len(word) + 1):
                row.append(min(row[j - 1] + 1, prev[j] + 1, prev[j - 1] + (word[j - 1] != ch)))
            self.cells += len(word)
            if node.key is not None and row[-1] <= k:
                out.append((node.key, node.value, row[-1]))
            if min(row) <= k:                        # else no extension can come back within k
                stack.extend((c, cc, row) for cc, c in node.children.items())
        out.sort(key=lambda t: (t[2], t[0]))
        return out
