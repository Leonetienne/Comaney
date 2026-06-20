"""
Sankey Studio: graph model, routing/partition algorithm, and generation.

See sankey-studio-spec.md for the full design rationale.

Node keys: "tag:<pk>" / "category:<pk>" / "project:<pk>" for real catalog
entities (all three types thrown into one pool), "connector:<token>" for an
explicit passthrough/junction node - a plain wiring shortcut with no
meaning of its own, used to collapse an M-to-N fan-in/fan-out into M+N
edges through one shared hub instead of M*N direct edges.

A node with outgoing edges whose wired children don't collectively claim
100% of its inflow simply keeps the rest for itself: node_totals (see
partition_flow) always reflects a node's full inflow regardless of what
happens to it downstream, whether that's all of it, none of it, or
anything in between. Nothing is ever auto-injected to force full
accounting.

Priority is a single integer owned by the node itself (not per-edge, not
per-parent): higher number is evaluated first whenever a parent is
partitioning its inflow among its children - the more specific/important
sibling should outrank the broader one it needs to intercept overlapping
expenses from. Ties break by origin type
(project > category > tag), then alphabetically by title. As a child,
a Connector node is always evaluated last regardless of its own priority
number (see build_children_order) and claims whatever inflow its
siblings didn't - as a parent, though, it's a normal node like any other:
it keeps whatever its own wired children don't claim, the same as any
Tag/Category/Project node would.

Routing/weight computation is a top-down, first-match-wins partition, not
independent per-edge sums: independent pairwise sums double-count whenever
a node has two children whose labels can both match the same expense
(e.g. one tagged both "Food" and "Drinks"), which makes it possible for
two children to jointly claim more than the parent actually received.
Partitioning avoids this by construction: every expense reaching a node is
handed, in full, to the first child (in priority order) whose label it
also matches; if it matches none of the wired children, it just stays at
the node. This is also why a node with multiple parents (e.g. a tag fed
both directly by a category and via an intermediate project) is safe: each
parent already claimed a disjoint subset of expenses before anything moved
downstream, so summing a node's inflow across its parents never
double-counts.

sum(inflow) == sum(outflow) is therefore only a guarantee when a node's
wired children happen to collectively cover its whole inflow - it is not a
general invariant the algorithm enforces, since a node is always free to
simply keep some or all of its own money. It does not apply to leaf nodes
either way (no outgoing edges at all): a leaf is a pure sink and just
accumulates whatever inflow arrives.

Because a Category (or Project) locks an expense to exactly one value,
that lock doesn't just block a *direct* edge between two different
Category nodes (is_impossible_edge) - it also blocks reaching a different
Category downstream through any chain of intermediate nodes, since a
Connector hub (and, just as much, a Tag node sitting in between) is a
transparent pass-through with no identity of its own to override it.
locked_identities/is_impossible_edge_chain compute this transitively so a
graph like "5 income Categories -> Connector -> 4 expense Categories" is
rejected with an explanation instead of silently routing every expense
that reaches the Connector nowhere at all.
"""
from decimal import Decimal

NODE_TYPE_RANK = {"project": 0, "category": 1, "tag": 2}
CATCH_ALL_TYPES = {"connector"}
# Category and Project are each singular per expense (never two different
# categories, or two different projects, on the same expense); Tag is the
# only multi-valued one. So an edge between two *different* nodes of the
# same one of these types can never have a matching expense on both ends.
_MUTUALLY_EXCLUSIVE_TYPES = {"category", "project"}


class CycleError(Exception):
    """Raised when a graph (or a proposed new edge) would not be a DAG."""


def parse_node_key(key: str) -> tuple[str, str]:
    """'tag:3' -> ('tag', '3'); 'connector:ab12' -> ('connector', 'ab12')."""
    node_type, _, ident = key.partition(":")
    return node_type, ident


def is_impossible_edge(source_type: str, target_type: str) -> bool:
    """True when an edge between these two node *types* could never carry
    any value, regardless of which specific nodes they are: e.g. two
    different Category nodes, since an expense's category is always
    exactly one value, so it can never match both ends of such an edge."""
    return source_type == target_type and source_type in _MUTUALLY_EXCLUSIVE_TYPES


def locked_identities(node_keys, edges) -> dict:
    """
    For every node, work out which specific Category/Project identity (if
    any) its inflow is provably already restricted to, by walking the DAG
    backward from real Category/Project nodes.

    A Category (or Project) node locks its *own* outflow to exactly its
    own identity, full stop, regardless of what fed into it - that's what
    "an expense's category is always exactly one value" means downstream,
    not just on the edge immediately touching the Category node. A node
    with no incoming edges (a root) is unrestricted. A node with incoming
    edges inherits the union of its parents' locks *only if every parent
    itself has a lock on that axis* - one unrestricted parent (e.g. a Tag
    root) means the node's inflow could still carry any identity, so nothing
    downstream of it can be ruled out on that basis alone.

    This is what makes a Connector hub transparent for this check (see the
    module docstring and CATCH_ALL_TYPES): it has no identity of its own,
    so its lock is derived purely from its parents, the same as any other
    pass-through node - a Tag node in the middle of a chain is exactly as
    "transparent" to this rule as a Connector is.

    Returns node_key -> {"category": frozenset(idents) | None,
                          "project": frozenset(idents) | None}.
    ``None`` means "not provably restricted" (could carry any identity on
    that axis). A frozenset means "provably restricted to one of these" -
    it can have more than one member when several different Category (or
    Project) roots converge on the same downstream node (e.g. 5 different
    Category nodes all wired into one Connector): every item is still
    locked to exactly one of them, just not all to the *same* one, and
    none of the 5 identities is available to any other Category node
    downstream (that would mean an expense holding two different
    categories at once).
    """
    parents: dict = {n: [] for n in node_keys}
    for s, t in edges:
        parents.setdefault(t, []).append(s)

    memo: dict = {}

    def resolve(node, axis):
        cache_key = (node, axis)
        if cache_key in memo:
            return memo[cache_key]
        memo[cache_key] = None  # cycle guard; real cycles are rejected elsewhere before this runs
        node_type, ident = parse_node_key(node)
        if node_type == axis:
            result = frozenset({ident})
        else:
            ps = parents.get(node, [])
            if not ps:
                result = None
            else:
                vals = [resolve(p, axis) for p in ps]
                result = None if any(v is None for v in vals) else frozenset().union(*vals)
        memo[cache_key] = result
        return result

    return {n: {axis: resolve(n, axis) for axis in _MUTUALLY_EXCLUSIVE_TYPES} for n in node_keys}


def is_impossible_edge_chain(source: str, target: str, locked: dict) -> bool:
    """Whether `target` (a real Category/Project node) could ever receive
    any flow from `source`, given `locked` (see locked_identities): true
    when source's inflow is provably already restricted - directly or
    through any chain of intermediate nodes, Connector or otherwise - to
    Category/Project identities that never include target's own. Subsumes
    is_impossible_edge's direct-edge check (for a direct edge,
    `locked[source]` reduces to exactly `source`'s own identity)."""
    target_type, target_ident = parse_node_key(target)
    if target_type not in _MUTUALLY_EXCLUSIVE_TYPES:
        return False
    src_lock = locked.get(source, {}).get(target_type)
    return src_lock is not None and target_ident not in src_lock


def topological_order(node_keys, edges) -> list:
    """Kahn's algorithm. `edges` is an iterable of (source, target) pairs
    over exactly `node_keys`. Raises CycleError if the graph isn't a DAG.
    Ties among simultaneously-ready nodes break alphabetically, so the
    result is deterministic (used by tests and diagnostics alike)."""
    node_keys = list(node_keys)
    children: dict = {n: [] for n in node_keys}
    indegree: dict = {n: 0 for n in node_keys}
    for s, t in edges:
        children[s].append(t)
        indegree[t] += 1

    ready = sorted(n for n in node_keys if indegree[n] == 0)
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        newly_ready = []
        for c in sorted(children[n]):
            indegree[c] -= 1
            if indegree[c] == 0:
                newly_ready.append(c)
        ready = sorted(ready + newly_ready)

    if len(order) != len(node_keys):
        raise CycleError("graph contains a cycle")
    return order


def would_create_cycle(node_keys, edges, new_edge) -> bool:
    """Whether adding `new_edge` (source, target) to `edges` would close a
    cycle. Used by the editor to reject a drawn edge at draw time."""
    try:
        topological_order(node_keys, list(edges) + [new_edge])
    except CycleError:
        return True
    return False


def _tie_break_key(node_key: str, node_types: dict, node_titles: dict):
    node_type = node_types.get(node_key, "tag")
    return (NODE_TYPE_RANK.get(node_type, len(NODE_TYPE_RANK)), node_titles.get(node_key, node_key))


def build_children_order(edges, priorities: dict, node_types: dict, node_titles: dict) -> dict:
    """
    For every node with at least one outgoing edge, build its children in
    final evaluation order: real children first (sorted by priority number
    descending - higher number evaluated first, then by _tie_break_key on
    ties), then a Connector child last, if the user wired one under this
    node - nothing is ever auto-injected. A node whose wired children
    don't collectively cover its whole inflow simply keeps the rest for
    itself; see partition_flow.

    Returns dict node_key -> ordered list of child node_keys.
    """
    children: dict = {}
    for s, t in edges:
        children.setdefault(s, []).append(t)

    result = {}
    for node, kids in children.items():
        real_kids = [k for k in kids if parse_node_key(k)[0] not in CATCH_ALL_TYPES]
        explicit_catch_all = next((k for k in kids if parse_node_key(k)[0] in CATCH_ALL_TYPES), None)
        real_kids.sort(key=lambda k: (-priorities.get(k, 0), _tie_break_key(k, node_types, node_titles)))
        result[node] = real_kids + [explicit_catch_all] if explicit_catch_all else real_kids
    return result


def partition_flow(children_order: dict, root_pools: dict, matches: dict) -> dict:
    """
    The core routing algorithm. Pure function, no Django/DB dependency.

    children_order: node_key -> ordered list of child node_keys, as built
                     by build_children_order. The last entry is a Connector
                     (matches[key] is None) only if the user explicitly
                     wired one under that node; otherwise every entry is a
                     normal node that only claims what it actually
                     matches, and whatever none of them claim simply stays
                     at the parent (see node_totals below).
    root_pools: root node_key -> list of (item_id, Decimal value): the
                intrinsic pool for nodes with no incoming edge.
    matches: node_key -> frozenset(item_id) for every node that appears as
             a child anywhere in children_order, or None for a Connector
             node (it has no expense data of its own to match against, so
             it always claims whatever its siblings didn't).

    Returns {"edge_weights": {(source, target): Decimal},
             "node_totals": {node_key: Decimal}}. node_totals is always a
             node's full inflow, whether or not all of it was claimed by
             a child - the gap between a node's node_totals and the sum of
             its own outgoing edge_weights is exactly what it kept.
    """
    all_nodes = set(children_order) | {c for kids in children_order.values() for c in kids} | set(root_pools)
    edges = [(n, c) for n, kids in children_order.items() for c in kids]
    order = topological_order(all_nodes, edges)

    inflow: dict = {n: [] for n in all_nodes}
    for root, pool in root_pools.items():
        inflow[root].extend(pool)

    edge_weights = {}
    node_totals = {}

    for node in order:
        bucket = inflow[node]
        node_totals[node] = sum((v for _, v in bucket), Decimal("0"))
        children = children_order.get(node, [])
        if not children:
            continue

        remaining = list(bucket)
        for child in children:
            child_matches = matches[child]
            if child_matches is None:
                claimed, remaining = remaining, []
            else:
                claimed = [item for item in remaining if item[0] in child_matches]
                remaining = [item for item in remaining if item[0] not in child_matches]
            edge_weights[(node, child)] = sum((v for _, v in claimed), Decimal("0"))
            inflow[child].extend(claimed)
        # Anything left in `remaining` after the last child just stays at
        # `node` - it's already counted in node_totals[node] above, and
        # there's nowhere it's required to go.

    return {"edge_weights": edge_weights, "node_totals": node_totals}


def prune_zero_weight(result: dict) -> dict:
    """Drop edges (and, transitively, nodes only reachable through them)
    with a computed weight of 0. Only affects the rendered snapshot, never
    the stored graph definition."""
    edge_weights = {e: w for e, w in result["edge_weights"].items() if w != 0}
    reachable = set()
    for s, t in edge_weights:
        reachable.add(s)
        reachable.add(t)
    node_totals = {n: v for n, v in result["node_totals"].items()
                   if v != 0 or n in reachable}
    return {"edge_weights": edge_weights, "node_totals": node_totals}
