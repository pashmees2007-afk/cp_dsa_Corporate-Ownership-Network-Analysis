"""Phase 6 - dense matrix operations for small cross-holding sub-networks.

Matrices are lists of rows. The sub-networks are strongly connected
components of at most a few dozen companies (the largest here is 11), so
plain O(k^3) multiplication is enough; NumPy is used only in the tests, to
check these results.
"""


def identity(k):
    return [[1.0 if i == j else 0.0 for j in range(k)] for i in range(k)]


def matmul(a, b):
    """a (n x m) times b (m x p). Skips zero entries of a, which is most of
    them in an ownership matrix."""
    p = len(b[0]) if b else 0
    out = [[0.0] * p for _ in a]
    for i, row in enumerate(a):
        acc = out[i]
        for t, x in enumerate(row):
            if x:
                bt = b[t]
                for j in range(p):
                    acc[j] += x * bt[j]
    return out


def add(a, b):
    return [[x + y for x, y in zip(ra, rb)] for ra, rb in zip(a, b)]


def matvec(a, v):
    return [sum(x * y for x, y in zip(row, v)) for row in a]


def max_abs(a):
    return max((abs(x) for row in a for x in row), default=0.0)


def walk_sum(a, tol=1e-15, max_iter=10_000):
    """(I + A + A^2 + A^3 + ..., number of terms added).

    Entry (i, j) of A^n is the total weight of all n-step walks from i to j,
    so the series sums the weight of walks of every length: the routes that
    go round a loop once, twice, and so on. It equals (I - A)^-1 and
    converges when the spectral radius of A is below 1, which holds for an
    ownership matrix unless some company is 100% held inside the loop. Terms
    are added until the newest one is below `tol` in every entry.
    """
    k = len(a)
    total, power = identity(k), identity(k)
    for n in range(1, max_iter + 1):
        power = matmul(power, a)
        total = add(total, power)
        if max_abs(power) < tol:
            return total, n
    raise ArithmeticError(f"walk sum did not converge in {max_iter} terms (a loop holds ~100%?)")
