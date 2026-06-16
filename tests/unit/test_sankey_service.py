"""
Unit tests for budget/sankey_service.py: the Sankey Studio routing
algorithm (topological ordering/cycle detection, priority-ordered child
sorting, and the first-match-wins inflow/outflow partition). Pure Python
logic, no Django/DB required.

Run with:
    venv/bin/pytest tests/unit/test_sankey_service.py -v
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from decimal import Decimal

import pytest

from budget.sankey_service import (
    CATCH_ALL_TYPES,
    CycleError,
    build_children_order,
    is_impossible_edge,
    is_impossible_edge_chain,
    locked_identities,
    parse_node_key,
    partition_flow,
    prune_zero_weight,
    topological_order,
    would_create_cycle,
)


class TestParseNodeKey:
    def test_real_node(self):
        assert parse_node_key("tag:3") == ("tag", "3")

    def test_connector_node(self):
        assert parse_node_key("connector:ab12") == ("connector", "ab12")


class TestTopologicalOrder:
    def test_simple_chain(self):
        order = topological_order(["a", "b", "c"], [("a", "b"), ("b", "c")])
        assert order == ["a", "b", "c"]

    def test_diamond_dag_is_fine(self):
        # a -> b -> d, a -> c -> d (multiple parents into d, no tree)
        nodes = ["a", "b", "c", "d"]
        edges = [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]
        order = topological_order(nodes, edges)
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_self_loop_is_a_cycle(self):
        with pytest.raises(CycleError):
            topological_order(["a"], [("a", "a")])

    def test_longer_cycle_is_detected(self):
        with pytest.raises(CycleError):
            topological_order(["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")])

    def test_disconnected_nodes_are_fine(self):
        order = topological_order(["a", "b"], [])
        assert set(order) == {"a", "b"}


class TestWouldCreateCycle:
    def test_detects_would_be_cycle(self):
        nodes = ["a", "b", "c"]
        edges = [("a", "b"), ("b", "c")]
        assert would_create_cycle(nodes, edges, ("c", "a")) is True

    def test_safe_edge_is_allowed(self):
        nodes = ["a", "b", "c"]
        edges = [("a", "b")]
        assert would_create_cycle(nodes, edges, ("a", "c")) is False


class TestBuildChildrenOrder:
    def test_sorts_by_priority_descending(self):
        edges = [("income", "grocers"), ("income", "vacation")]
        priorities = {"grocers": 2, "vacation": 1}
        node_types = {"grocers": "tag", "vacation": "tag"}
        result = build_children_order(edges, priorities, node_types, {})
        assert result["income"] == ["grocers", "vacation"]

    def test_tie_break_by_type_then_alpha(self):
        edges = [("income", "tag:zzz"), ("income", "project:aaa"), ("income", "category:bbb")]
        priorities = {"tag:zzz": 1, "project:aaa": 1, "category:bbb": 1}
        node_types = {"tag:zzz": "tag", "project:aaa": "project", "category:bbb": "category"}
        titles = {"tag:zzz": "zzz", "project:aaa": "aaa", "category:bbb": "bbb"}
        result = build_children_order(edges, priorities, node_types, titles)
        # project beats category beats tag on a priority tie
        assert result["income"] == ["project:aaa", "category:bbb", "tag:zzz"]

    def test_no_catch_all_is_ever_auto_injected(self):
        # A node whose real child doesn't cover everything used to get an
        # implicit "<node>::auto_other" appended; that mechanism is gone
        # entirely now, for every node, always -- nothing is ever injected.
        edges = [("income", "grocers")]
        result = build_children_order(edges, {}, {"grocers": "tag"}, {})
        assert result["income"] == ["grocers"]

    def test_leaf_node_has_no_entry(self):
        result = build_children_order([("a", "b")], {}, {}, {})
        assert "b" not in result

    def test_explicit_connector_node_used_as_catch_all(self):
        # An explicitly user-wired Connector is still respected as a
        # catch-all: always sorted last, regardless of priority number.
        edges = [("income", "connector:hub"), ("income", "grocers")]
        priorities = {"connector:hub": 0, "grocers": 5}
        result = build_children_order(edges, priorities, {"grocers": "tag"}, {})
        assert result["income"] == ["grocers", "connector:hub"]


class TestIsImpossibleEdge:
    def test_different_categories_is_impossible(self):
        assert is_impossible_edge("category", "category") is True

    def test_different_projects_is_impossible(self):
        assert is_impossible_edge("project", "project") is True

    def test_tag_to_tag_is_fine(self):
        assert is_impossible_edge("tag", "tag") is False

    def test_category_to_tag_is_fine(self):
        assert is_impossible_edge("category", "tag") is False

    def test_category_to_project_is_fine(self):
        assert is_impossible_edge("category", "project") is False

    def test_category_to_connector_is_fine(self):
        assert is_impossible_edge("category", "connector") is False


class TestLockedIdentities:
    def test_root_is_unrestricted(self):
        locked = locked_identities(["tag:1"], [])
        assert locked["tag:1"]["category"] is None
        assert locked["tag:1"]["project"] is None

    def test_category_node_locks_to_its_own_ident_regardless_of_parents(self):
        # Even a Category node with an (impossible in practice, but the
        # function shouldn't care) tag parent is locked to its own ident.
        locked = locked_identities(["tag:1", "category:9"], [("tag:1", "category:9")])
        assert locked["category:9"]["category"] == frozenset({"9"})

    def test_lock_propagates_through_a_tag_intermediary(self):
        # category:5 -> tag:1: tag:1's inflow is provably all category 5.
        nodes = ["category:5", "tag:1"]
        edges = [("category:5", "tag:1")]
        locked = locked_identities(nodes, edges)
        assert locked["tag:1"]["category"] == frozenset({"5"})

    def test_lock_propagates_through_a_connector(self):
        # This is the exact shape that broke a real diagram: one Category
        # root wired through a Connector hub.
        nodes = ["category:5", "connector:hub"]
        edges = [("category:5", "connector:hub")]
        locked = locked_identities(nodes, edges)
        assert locked["connector:hub"]["category"] == frozenset({"5"})

    def test_multiple_category_roots_converge_into_a_multi_member_lock(self):
        # 3 different income Categories all wired into one Connector: every
        # item is still locked to *one* of them, just not all the same one.
        nodes = ["category:1", "category:2", "category:3", "connector:hub"]
        edges = [
            ("category:1", "connector:hub"),
            ("category:2", "connector:hub"),
            ("category:3", "connector:hub"),
        ]
        locked = locked_identities(nodes, edges)
        assert locked["connector:hub"]["category"] == frozenset({"1", "2", "3"})

    def test_one_unrestricted_parent_unlocks_the_whole_node(self):
        # connector fed by a locked Category root AND an unrestricted Tag
        # root: some of its inflow could carry any category, so it must
        # not be treated as provably restricted.
        nodes = ["category:1", "tag:9", "connector:hub"]
        edges = [("category:1", "connector:hub"), ("tag:9", "connector:hub")]
        locked = locked_identities(nodes, edges)
        assert locked["connector:hub"]["category"] is None

    def test_project_axis_is_independent_of_category_axis(self):
        # Two separate single-parent chains, one per axis: a Project parent
        # carries no category information at all (Category and Project are
        # orthogonal fields on an expense), so it must not affect a node's
        # category lock, and vice versa.
        nodes = ["category:5", "project:2", "tag:1", "tag:2"]
        edges = [("category:5", "tag:1"), ("project:2", "tag:2")]
        locked = locked_identities(nodes, edges)
        assert locked["tag:1"]["category"] == frozenset({"5"})
        assert locked["tag:1"]["project"] is None
        assert locked["tag:2"]["project"] == frozenset({"2"})
        assert locked["tag:2"]["category"] is None

    def test_connector_fed_by_both_a_category_and_a_project_root_is_unlocked_on_category(self):
        # A Project parent carries no category restriction, so mixing it
        # into a Connector alongside a Category parent means some of the
        # connector's inflow could carry any category -- the connector must
        # not be treated as provably locked to the Category parent's ident.
        nodes = ["category:5", "project:2", "connector:hub"]
        edges = [("category:5", "connector:hub"), ("project:2", "connector:hub")]
        locked = locked_identities(nodes, edges)
        assert locked["connector:hub"]["category"] is None
        assert locked["connector:hub"]["project"] is None


class TestIsImpossibleEdgeChain:
    def test_direct_category_to_different_category_is_impossible(self):
        locked = locked_identities(["category:1", "category:2"], [])
        assert is_impossible_edge_chain("category:1", "category:2", locked) is True

    def test_category_through_connector_to_different_category_is_impossible(self):
        # The real-world bug: 5 income Categories -> Connector -> 4 expense
        # Categories. Every connector -> category edge is impossible.
        nodes = ["category:149", "connector:hub", "category:20"]
        edges = [("category:149", "connector:hub"), ("connector:hub", "category:20")]
        locked = locked_identities(nodes, edges)
        assert is_impossible_edge_chain("connector:hub", "category:20", locked) is True

    def test_category_through_tag_to_different_category_is_impossible(self):
        # Same underlying issue, no Connector/Other involved at all: any
        # real intermediate node is just as "transparent" to the lock.
        nodes = ["category:1", "tag:9", "category:2"]
        edges = [("category:1", "tag:9"), ("tag:9", "category:2")]
        locked = locked_identities(nodes, edges)
        assert is_impossible_edge_chain("tag:9", "category:2", locked) is True

    def test_category_through_connector_to_tag_is_fine(self):
        # The legitimate use of a Connector: fanning Categories out to Tags
        # never conflicts (Tag isn't a mutually-exclusive axis).
        nodes = ["category:1", "connector:hub", "tag:9"]
        edges = [("category:1", "connector:hub"), ("connector:hub", "tag:9")]
        locked = locked_identities(nodes, edges)
        assert is_impossible_edge_chain("connector:hub", "tag:9", locked) is False

    def test_multi_root_convergence_still_blocks_an_unrelated_category(self):
        nodes = ["category:1", "category:2", "connector:hub", "category:3"]
        edges = [
            ("category:1", "connector:hub"),
            ("category:2", "connector:hub"),
            ("connector:hub", "category:3"),
        ]
        locked = locked_identities(nodes, edges)
        assert is_impossible_edge_chain("connector:hub", "category:3", locked) is True

    def test_mixed_locked_and_unlocked_parent_does_not_block(self):
        # Because part of the connector's inflow is unrestricted (from the
        # Tag root), it could still legitimately reach a Category target.
        nodes = ["category:1", "tag:9", "connector:hub", "category:2"]
        edges = [
            ("category:1", "connector:hub"),
            ("tag:9", "connector:hub"),
            ("connector:hub", "category:2"),
        ]
        locked = locked_identities(nodes, edges)
        assert is_impossible_edge_chain("connector:hub", "category:2", locked) is False

    def test_project_target_uses_the_project_axis(self):
        nodes = ["project:1", "connector:hub", "project:2"]
        edges = [("project:1", "connector:hub"), ("connector:hub", "project:2")]
        locked = locked_identities(nodes, edges)
        assert is_impossible_edge_chain("connector:hub", "project:2", locked) is True

    def test_tag_target_is_never_impossible(self):
        locked = locked_identities(["category:1", "tag:2"], [("category:1", "tag:2")])
        assert is_impossible_edge_chain("category:1", "tag:2", locked) is False


class TestPartitionFlow:
    def test_spec_worked_example(self):
        """
        Income(2000) -> Beach Week(priority 2, matches project=beach-week) -> Grocers(100)
        Income(2000) -> Grocers direct(priority 1, matches tag=grocers)
        Grocers total inflow must be exactly 400 (100 via Beach Week + 300 direct),
        no expense double-counted across the two parents.
        """
        # 8 expenses on "Income": some project=beach-week, some tag=grocers, overlapping subset
        # is both. Beach Week claims project=beach-week first (600 total); of that, the ones
        # also tagged grocers (100) flow onward. The remaining 1400 is checked against the
        # direct Grocers edge, of which 300 match tag=grocers.
        bw_only = [(f"bw{i}", Decimal("100")) for i in range(5)]        # 500, beach week only
        bw_and_grocers = [("bwg0", Decimal("100"))]                      # 100, beach week + grocers
        direct_grocers = [(f"g{i}", Decimal("100")) for i in range(3)]   # 300, grocers only (no project)
        rest = [(f"r{i}", Decimal("100")) for i in range(11)]            # 1100, matches neither

        income_pool = bw_only + bw_and_grocers + direct_grocers + rest
        assert sum(v for _, v in income_pool) == Decimal("2000")

        beach_week_matches = frozenset(iid for iid, _ in bw_only + bw_and_grocers)  # 600
        grocers_matches = frozenset(iid for iid, _ in bw_and_grocers + direct_grocers)  # matches tag=grocers

        children_order = {
            "income": ["beachweek", "grocers"],
            "beachweek": ["grocers"],
        }
        root_pools = {"income": income_pool}
        matches = {
            "beachweek": beach_week_matches,
            "grocers": grocers_matches,
        }

        result = partition_flow(children_order, root_pools, matches)

        assert result["edge_weights"][("income", "beachweek")] == Decimal("600")
        assert result["edge_weights"][("beachweek", "grocers")] == Decimal("100")
        assert result["edge_weights"][("income", "grocers")] == Decimal("300")
        assert result["node_totals"]["grocers"] == Decimal("400")

    def test_leaf_node_is_exempt_from_conservation(self):
        # Grocers is a leaf (no outgoing edges): it just accumulates inflow.
        children_order = {"income": ["grocers"]}
        root_pools = {"income": [("e1", Decimal("50")), ("e2", Decimal("50"))]}
        matches = {"grocers": frozenset({"e1"})}
        result = partition_flow(children_order, root_pools, matches)
        assert result["node_totals"]["grocers"] == Decimal("50")
        assert "grocers" not in children_order  # confirms it's genuinely a leaf here

    def test_multi_parent_node_sums_without_double_counting(self):
        children_order = {
            "a": ["shared"],
            "b": ["shared"],
        }
        root_pools = {
            "a": [("x1", Decimal("10")), ("x2", Decimal("10"))],
            "b": [("y1", Decimal("20")), ("y2", Decimal("20"))],
        }
        matches = {"shared": frozenset({"x1", "y1"})}
        result = partition_flow(children_order, root_pools, matches)
        # 10 (x1 via a) + 20 (y1 via b) = 30, each expense counted exactly once
        assert result["node_totals"]["shared"] == Decimal("30")

    def test_unmatched_remainder_never_raises_and_stays_at_the_node(self):
        # A node's wired child doesn't have to cover everything: whatever
        # it doesn't claim simply stays at the parent (already reflected
        # in node_totals, computed as its full inflow) -- no catch-all is
        # required, and nothing is ever raised for the "leftover".
        children_order = {"income": ["grocers"]}
        root_pools = {"income": [("e1", Decimal("50")), ("e2", Decimal("50"))]}
        matches = {"grocers": frozenset({"e1"})}
        result = partition_flow(children_order, root_pools, matches)
        assert result["node_totals"]["income"] == Decimal("100")
        assert result["edge_weights"][("income", "grocers")] == Decimal("50")
        # The other 50 is implicitly "kept" at income: no edge carries it.

    def test_no_matching_children_keeps_everything(self):
        # "Consume all" case: a child that matches nothing leaves the
        # parent's full inflow kept at the parent, effectively behaving
        # like a true leaf despite the drawn edge.
        children_order = {"income": ["grocers"]}
        root_pools = {"income": [("e1", Decimal("100"))]}
        matches = {"grocers": frozenset()}
        result = partition_flow(children_order, root_pools, matches)
        assert result["node_totals"]["income"] == Decimal("100")
        assert result["edge_weights"][("income", "grocers")] == Decimal("0")

    def test_fully_matching_children_passes_everything(self):
        # "Pass all along" case: children between them claim it all, so
        # nothing is kept at the parent.
        children_order = {"income": ["grocers"]}
        root_pools = {"income": [("e1", Decimal("100")), ("e2", Decimal("50"))]}
        matches = {"grocers": frozenset({"e1", "e2"})}
        result = partition_flow(children_order, root_pools, matches)
        assert result["node_totals"]["income"] == Decimal("150")
        assert result["edge_weights"][("income", "grocers")] == Decimal("150")

    def test_end_to_end_no_catch_all_appears_anywhere(self):
        # Full pipeline (build_children_order -> partition_flow), the same
        # two steps sankey_generation.generate() chains together: a real
        # child that only partially matches must produce NO trace of a
        # catch-all node anywhere in the final node/edge output -- there
        # is no "Other" node type, and nothing is ever auto-injected.
        edges = [("category:1", "tag:9")]
        node_types = {"tag:9": "tag"}
        children_order = build_children_order(edges, {}, node_types, {})
        root_pools = {"category:1": [("e1", Decimal("60")), ("e2", Decimal("40"))]}
        matches = {"tag:9": frozenset({"e1"})}
        result = partition_flow(children_order, root_pools, matches)

        assert set(result["node_totals"]) == {"category:1", "tag:9"}
        assert set(result["edge_weights"]) == {("category:1", "tag:9")}
        assert result["node_totals"]["category:1"] == Decimal("100")
        assert result["node_totals"]["tag:9"] == Decimal("60")
        for key in list(result["node_totals"]) + [t for _, t in result["edge_weights"]]:
            node_type, _ = parse_node_key(key)
            assert node_type not in CATCH_ALL_TYPES


class TestPruneZeroWeight:
    def test_drops_zero_weight_edges_and_orphaned_nodes(self):
        result = {
            "edge_weights": {("a", "b"): Decimal("0"), ("a", "c"): Decimal("50")},
            "node_totals": {"a": Decimal("50"), "b": Decimal("0"), "c": Decimal("50")},
        }
        pruned = prune_zero_weight(result)
        assert ("a", "b") not in pruned["edge_weights"]
        assert ("a", "c") in pruned["edge_weights"]
        assert "b" not in pruned["node_totals"]
        assert pruned["node_totals"]["a"] == Decimal("50")
