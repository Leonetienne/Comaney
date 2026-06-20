"""
Django/DB-facing layer for Sankey Studio: loading/saving a feuser's graph
definition, and generating a chart snapshot from real expense data.

Deliberately kept separate from budget/sankey_service.py, which holds the
pure routing algorithm (no Django/DB dependency, unit-testable on its own).

Node identity matching (`_resolve_node_q` below) mirrors the same "own
tags/category if owner, else feuser's own
ExpenseDataOverlay, never the foreign owner's" visibility rule already
implemented in `query_parser._tag_q`/`_cat_q` (see that module's module-
level docs for the other two shapes it must stay in sync with). It is not
reused verbatim: `_tag_q`/`_cat_q` match a title *substring* for the
free-text query language, whereas a Sankey node needs an *exact* match
against one specific, already-known Tag/Category row - reusing the
substring version here would risk false positives (e.g. a "Food" node
also matching an expense tagged "Fast Food"). This is a new shape the
existing four don't cover, not a fifth copy of one of them; full
unification of all five is left for a follow-up rather than attempted
under this change, given the size/regression-risk of touching the
existing four call sites versus the size of this feature itself.
"""
import json

from django.db.models import Q

from .models import Category, Expense, SankeyGraph, Tag, TransactionType
from .sankey_service import (
    CATCH_ALL_TYPES,
    build_children_order,
    is_impossible_edge,
    is_impossible_edge_chain,
    locked_identities,
    parse_node_key,
    partition_flow,
    prune_zero_weight,
)

_CATCH_ALL_DEFAULT_LABEL = {"connector": "Connector"}


class SankeyValidationError(Exception):
    """Raised when a graph can't be generated as currently defined."""


def node_key(node_type: str, pk) -> str:
    return f"{node_type}:{pk}"


def catalog_for_feuser(feuser) -> dict:
    """Every Tag/Category/Project available to this feuser, keyed by node
    key -> {"type", "title"}. Projects: non-archived ones the feuser is a
    member of (a Sankey diagram is a personal artifact; archived projects
    can't gain new members/expenses anyway)."""
    catalog = {}
    for tag in Tag.objects.filter(owning_feuser=feuser):
        catalog[node_key("tag", tag.pk)] = {"type": "tag", "title": tag.title}
    for cat in Category.objects.filter(owning_feuser=feuser):
        catalog[node_key("category", cat.pk)] = {"type": "category", "title": cat.title}

    from buddies.models import Project, ProjectMember
    project_ids = (
        ProjectMember.objects.filter(feuser=feuser, group__archived=False)
        .values_list("group_id", flat=True)
    )
    for project in Project.objects.filter(pk__in=project_ids):
        catalog[node_key("project", project.pk)] = {"type": "project", "title": project.name}
    return catalog


def _load_config(graph: SankeyGraph) -> dict:
    try:
        config = json.loads(graph.config_json or "{}")
    except (json.JSONDecodeError, ValueError):
        config = {}
    config.setdefault("nodes", {})
    config.setdefault("edges", [])
    return config


def get_or_create_graph(feuser) -> SankeyGraph:
    graph, _ = SankeyGraph.objects.get_or_create(feuser=feuser)
    return graph


def load_editor_state(feuser) -> dict:
    """Everything the editor page needs: the saved graph plus, for every
    catalog entity, whether it's placed/unplaced (a deleted/archived
    entity that's still referenced by a saved node is silently dropped
    from the "placed" view here - it can no longer be wired or generated
    against, same as unplaced)."""
    graph = get_or_create_graph(feuser)
    config = _load_config(graph)
    catalog = catalog_for_feuser(feuser)

    nodes_config = {k: v for k, v in config["nodes"].items()
                     if parse_node_key(k)[0] in CATCH_ALL_TYPES or k in catalog}
    edges_config = [e for e in config["edges"]
                     if e["source"] in nodes_config and e["target"] in nodes_config]

    unplaced = sorted(k for k in catalog if k not in nodes_config)
    return {
        "catalog": catalog,
        "nodes": nodes_config,
        "edges": edges_config,
        "unplaced": unplaced,
    }


def _check_impossible_chains(node_keys, edges) -> None:
    """Raises SankeyValidationError for the first edge that could never
    carry any value because the source's inflow is already provably
    locked to a different Category/Project - whether that's a direct edge
    (is_impossible_edge's case) or reached through a chain of
    intermediate nodes, Connector or otherwise (see
    sankey_service.locked_identities)."""
    locked = locked_identities(node_keys, edges)
    for s, t in edges:
        if is_impossible_edge_chain(s, t, locked):
            t_type, _ = parse_node_key(t)
            raise SankeyValidationError(
                f"{s} -> {t}: money reaching {s} is already committed to a different {t_type} "
                "earlier in this diagram (directly, or through a chain of intermediate nodes), "
                f"so it can never also match {t}; an expense's {t_type} is always exactly one "
                "value. This connection could never carry any value."
            )


def save_graph(feuser, nodes: dict, edges: list) -> None:
    """Persist the abstract graph. Validates the DAG constraint (no
    cycles) and rejects edges that could never carry any value, before
    saving; does not touch real expense data."""
    node_keys = list(nodes.keys())
    edge_pairs = [(e["source"], e["target"]) for e in edges]
    for s, t in edge_pairs:
        if s not in nodes or t not in nodes:
            raise SankeyValidationError(f"Edge references an unplaced node: {s} -> {t}")
        s_type, _ = parse_node_key(s)
        t_type, _ = parse_node_key(t)
        if is_impossible_edge(s_type, t_type):
            raise SankeyValidationError(
                f"{s} -> {t}: an expense's {s_type} is always exactly one value, "
                f"so a {s_type} can never co-occur with a different {t_type} on the "
                "same expense; this edge could never carry any value."
            )

    from .sankey_service import CycleError, topological_order
    try:
        topological_order(node_keys, edge_pairs)
    except CycleError:
        raise SankeyValidationError("That graph contains a cycle; Sankey Studio requires a DAG.")

    _check_impossible_chains(node_keys, edge_pairs)

    graph = get_or_create_graph(feuser)
    graph.config_json = json.dumps({"nodes": nodes, "edges": edges})
    graph.save(update_fields=["config_json"])


def _resolve_node_q(node_type: str, ident, feuser) -> Q:
    """Own-if-owner-else-overlay exact-match Q for one real node. See
    module docstring for why this isn't just `query_parser._tag_q`/`_cat_q`."""
    if node_type == "tag":
        owned = Q(owning_feuser=feuser, tags__pk=ident)
        overlay = Q(pk__in=Expense.objects.filter(
            data_overlays__feuser=feuser, data_overlays__tags__pk=ident,
        ).exclude(owning_feuser=feuser).values("pk"))
        return owned | overlay
    if node_type == "category":
        owned = Q(owning_feuser=feuser, category_id=ident)
        overlay = Q(pk__in=Expense.objects.filter(
            data_overlays__feuser=feuser, data_overlays__category_id=ident,
        ).exclude(owning_feuser=feuser).values("pk"))
        return owned | overlay
    if node_type == "project":
        return Q(project_id=ident)
    raise ValueError(f"unknown node type {node_type!r}")


def _scoped_expense_qs(feuser, start, end, sharing: str):
    """Same period + individual/shared scoping already used by the
    dashboard (see budget/views/dashboard_cards_api.py::_period_qs and
    budget/views/_sharing.py::build_shared_qs), reused rather than
    reimplemented. Sankey Studio is a spending-flow diagram, not a general
    ledger view, so it's further restricted to real spending
    (type=TransactionType.EXPENSE) - income and savings deposits/
    withdrawals are money movements, not "spend" a Category/Tag/Project
    graph is meant to route."""
    from .views._sharing import build_shared_qs
    if sharing == "shared":
        return build_shared_qs(feuser, start, end).filter(type=TransactionType.EXPENSE)
    return Expense.objects.filter(
        owning_feuser=feuser, date_due__gte=start, date_due__lte=end,
        deactivated=False, is_dummy=False, type=TransactionType.EXPENSE,
    )


def generate(feuser, start, end, sharing: str) -> dict:
    """Run the routing algorithm against real expense data and return a
    render-ready {"nodes": [...], "links": [...]} snapshot. Catalog items
    that aren't placed on the canvas are simply excluded from the graph,
    the same as a disabled node -- they're skipped silently rather than
    blocking generation, since a diagram is normally built up incrementally
    and shouldn't be unusable while it's incomplete."""
    state = load_editor_state(feuser)

    nodes_config = state["nodes"]
    catalog = state["catalog"]
    enabled_keys = {k for k, cfg in nodes_config.items() if not cfg.get("disabled", False)}
    active_edges = [(e["source"], e["target"]) for e in state["edges"]
                    if e["source"] in enabled_keys and e["target"] in enabled_keys]
    _check_impossible_chains(list(enabled_keys), active_edges)

    priorities = {k: cfg.get("priority", 0) for k, cfg in nodes_config.items()}
    node_types, node_titles = {}, {}
    for k in enabled_keys:
        node_type, _ = parse_node_key(k)
        if node_type in CATCH_ALL_TYPES:
            node_types[k] = node_type
            node_titles[k] = nodes_config[k].get("label", _CATCH_ALL_DEFAULT_LABEL[node_type])
        else:
            node_types[k] = catalog[k]["type"]
            node_titles[k] = catalog[k]["title"]

    children_order = build_children_order(active_edges, priorities, node_types, node_titles)

    value_field = "effective_value" if sharing == "shared" else "value"
    qs = _scoped_expense_qs(feuser, start, end, sharing)
    values_by_pk = {row["pk"]: row[value_field] for row in qs.values("pk", value_field)}

    matches = {}
    for key in enabled_keys:
        node_type, ident = parse_node_key(key)
        if node_type in CATCH_ALL_TYPES:
            matches[key] = None
            continue
        q = _resolve_node_q(node_type, ident, feuser)
        matches[key] = frozenset(qs.filter(q).values_list("pk", flat=True))

    indegree = {k: 0 for k in enabled_keys}
    for s, t in active_edges:
        indegree[t] = indegree.get(t, 0) + 1

    root_pools = {}
    for key in enabled_keys:
        node_type, _ = parse_node_key(key)
        if node_type in CATCH_ALL_TYPES or indegree.get(key, 0) != 0:
            continue
        root_pools[key] = [(pk, values_by_pk[pk]) for pk in matches[key] if pk in values_by_pk]

    result = prune_zero_weight(partition_flow(children_order, root_pools, matches))

    nodes_out = [
        {"key": k, "title": node_titles[k], "value": float(v),
         "color": (nodes_config.get(k) or {}).get("color")}
        for k, v in result["node_totals"].items()
    ]
    links_out = [
        {"source": s, "target": t, "value": float(v)}
        for (s, t), v in result["edge_weights"].items()
    ]
    return {"nodes": nodes_out, "links": links_out}
