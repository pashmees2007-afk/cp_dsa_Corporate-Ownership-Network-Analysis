"""Phase 6 - resolved chains stored as trees rooted at beneficial owners.

Phase 4 finds a company's chains by walking up from the company. Here each
chain is stored the other way round, from its terminal owner down to the
company, and chains that start at the same owner share one tree: the owner is
the root, each child is a company that the parent holds shares in, and the
path from the root to a node is one resolved chain. Tata Sons -> Tata
Investment Corporation is stored once, however many chains continue below it.

    forest = OwnershipForest.from_chains(all_chains)
    forest.chains_of(company)   # chains of one company, without traversing the graph
    forest.portfolio(owner)     # every company an owner reaches, with effective stakes

Each node keeps a parent pointer, and an index maps every entity to the tree
nodes where it appears. So the chains of a company are found by looking the
company up in the index and following parent pointers to the root: O(total
length of its chains), with no graph traversal.

Only chains that end at a beneficial owner (a natural person or an entity
with no recorded owner) are stored: a circular chain has no owner at its
root, and a below-threshold chain was not resolved to one.
"""
from .chains import NATURAL_PERSON, NO_RECORDED_OWNER, Chain


class TreeNode:
    __slots__ = ("entity", "stake", "effective", "parent", "children", "chain_ends")

    def __init__(self, entity, stake, effective, parent):
        self.entity = entity         # entity ID
        self.stake = stake           # stake of the parent in this entity (1.0 at a root)
        self.effective = effective   # product of stakes from the root down to here
        self.parent = parent
        self.children = {}           # entity ID -> TreeNode
        self.chain_ends = None       # end reason if a stored chain ends here

    def path(self):
        """Entity IDs from this node up to the root."""
        out, node = [], self
        while node is not None:
            out.append(node.entity)
            node = node.parent
        return out


class OwnershipForest:
    def __init__(self):
        self.roots = {}              # owner entity ID -> root TreeNode
        self.index = {}              # entity ID -> [TreeNode] where it appears
        self.chains_stored = 0

    def _node(self, parent, entity, stake):
        child = parent.children.get(entity)
        if child is None:
            child = TreeNode(entity, stake, parent.effective * stake, parent)
            parent.children[entity] = child
            self.index.setdefault(entity, []).append(child)
        return child

    def add(self, chain):
        """Store one Phase 4 chain. Returns False (and stores nothing) for a
        chain that does not end at a beneficial owner."""
        if chain.end not in (NATURAL_PERSON, NO_RECORDED_OWNER):
            return False
        owner = chain.terminal
        node = self.roots.get(owner)
        if node is None:
            node = self.roots[owner] = TreeNode(owner, 1.0, 1.0, None)
            self.index.setdefault(owner, []).append(node)
        # the chain runs company -> ... -> owner; store it owner -> ... -> company
        for entity, stake in zip(reversed(chain.nodes[:-1]), reversed(chain.stakes)):
            node = self._node(node, entity, stake)
        node.chain_ends = chain.end
        self.chains_stored += 1
        return True

    @classmethod
    def from_chains(cls, chains):
        forest = cls()
        for c in chains:
            forest.add(c)
        return forest

    def chains_of(self, company):
        """The stored chains of `company` as Phase 4 Chain objects, highest
        effective stake first. Found from the index and parent pointers only."""
        out = []
        for node in self.index.get(company, ()):
            if node.chain_ends is None or node.parent is None:
                continue
            nodes, stakes, n = [], [], node
            while n is not None:
                nodes.append(n.entity)
                if n.parent is not None:
                    stakes.append(n.stake)
                n = n.parent
            out.append(Chain(tuple(nodes), tuple(stakes), node.effective, node.chain_ends))
        return sorted(out, key=lambda c: (-c.effective, c.layers, c.nodes))

    def portfolio(self, owner):
        """{company ID: summed effective stake} over every stored chain in
        `owner`'s tree: what the owner reaches, and how much of it."""
        root = self.roots.get(owner)
        if root is None:
            return {}
        totals, stack = {}, list(root.children.values())
        while stack:
            node = stack.pop()
            if node.chain_ends is not None:
                totals[node.entity] = totals.get(node.entity, 0.0) + node.effective
            stack.extend(node.children.values())
        return totals

    def node_count(self):
        return sum(len(v) for v in self.index.values())
