import random
import string
import unittest

from ownership.similarity import levenshtein, similarity
from ownership.trie import Trie


class Levenshtein(unittest.TestCase):
    def test_known_distances(self):
        cases = [("", "", 0), ("", "abc", 3), ("abc", "", 3), ("abc", "abc", 0),
                 ("kitten", "sitting", 3), ("flaw", "lawn", 2), ("educaton", "education", 1),
                 ("governement", "government", 1), ("mid", "small", 4)]
        for a, b, d in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(levenshtein(a, b), d)
                self.assertEqual(levenshtein(b, a), d)

    def test_limit_returns_exact_distance_within_limit(self):
        self.assertEqual(levenshtein("kitten", "sitting", limit=3), 3)
        self.assertEqual(levenshtein("kitten", "sitting", limit=10), 3)

    def test_limit_returns_limit_plus_one_beyond_it(self):
        self.assertEqual(levenshtein("kitten", "sitting", limit=2), 3)
        self.assertEqual(levenshtein("a", "abcdefgh", limit=2), 3)       # length gap alone
        self.assertEqual(levenshtein("abcdef", "uvwxyz", limit=1), 2)

    def test_limit_agrees_with_full_computation(self):
        rng = random.Random(7)
        for _ in range(300):
            a = "".join(rng.choices("abc ", k=rng.randint(0, 8)))
            b = "".join(rng.choices("abc ", k=rng.randint(0, 8)))
            k = rng.randint(0, 4)
            d = levenshtein(a, b)
            self.assertEqual(levenshtein(a, b, limit=k), d if d <= k else k + 1)

    def test_similarity(self):
        self.assertEqual(similarity("", ""), 1.0)
        self.assertEqual(similarity("abc", "abc"), 1.0)
        self.assertEqual(similarity("abc", "xyz"), 0.0)
        self.assertAlmostEqual(similarity("holding", "holdings"), 7 / 8)


class TrieBasics(unittest.TestCase):
    def setUp(self):
        self.t = Trie()
        for i, w in enumerate(["tata", "tata sons", "tata steel", "tata power", "titan", "trent"]):
            self.t.insert(w, i)

    def test_size_and_membership(self):
        self.assertEqual(len(self.t), 6)
        self.assertIn("tata sons", self.t)
        self.assertNotIn("tata s", self.t)          # a prefix, not a key
        self.assertNotIn("tatas", self.t)

    def test_get(self):
        self.assertEqual(self.t.get("titan"), 4)
        self.assertIsNone(self.t.get("tit"))
        self.assertEqual(self.t.get("nope", "x"), "x")

    def test_reinsert_updates_value_not_size(self):
        self.t.insert("titan", 99)
        self.assertEqual((len(self.t), self.t.get("titan")), (6, 99))

    def test_prefix_is_sorted_and_complete(self):
        self.assertEqual([k for k, _ in self.t.with_prefix("tata")],
                         ["tata", "tata power", "tata sons", "tata steel"])
        self.assertEqual([k for k, _ in self.t.with_prefix("tata s")], ["tata sons", "tata steel"])
        self.assertEqual(self.t.with_prefix("x"), [])
        self.assertEqual(len(self.t.with_prefix("")), 6)

    def test_within(self):
        self.assertEqual([(k, d) for k, _, d in self.t.within("tata sons", 0)], [("tata sons", 0)])
        self.assertEqual({k for k, _, _ in self.t.within("tata sonz", 1)}, {"tata sons"})
        self.assertEqual({k for k, _, _ in self.t.within("tata steal", 2)}, {"tata steel"})
        self.assertEqual(self.t.within("zzzzzz", 2), [])

    def test_empty_key(self):
        t = Trie()
        t.insert("", "root")
        t.insert("a", "a")
        self.assertEqual(t.get(""), "root")
        self.assertEqual({k for k, _, _ in t.within("", 1)}, {"", "a"})


class TrieNearMatchIsExact(unittest.TestCase):
    """within() must return exactly the keys a brute-force scan finds."""

    def test_against_brute_force(self):
        rng = random.Random(17)
        words = {"".join(rng.choices(string.ascii_lowercase[:5] + " ", k=rng.randint(1, 10)))
                 for _ in range(300)}
        t = Trie()
        for w in words:
            t.insert(w)
        for _ in range(100):
            q = "".join(rng.choices(string.ascii_lowercase[:5] + " ", k=rng.randint(1, 10)))
            k = rng.randint(0, 3)
            expected = sorted((levenshtein(q, w), w) for w in words if levenshtein(q, w) <= k)
            got = sorted((d, key) for key, _, d in t.within(q, k))
            self.assertEqual(got, expected, (q, k))

    def test_pruning_does_less_work_than_brute_force(self):
        rng = random.Random(3)
        words = {"".join(rng.choices(string.ascii_lowercase, k=12)) for _ in range(500)}
        t = Trie()
        for w in words:
            t.insert(w)
        q = "abcdefghijkl"
        t.within(q, 2)
        self.assertLess(t.cells, sum(len(q) * len(w) for w in words) / 5)


if __name__ == "__main__":
    unittest.main()
