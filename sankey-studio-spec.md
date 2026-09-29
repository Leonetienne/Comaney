# Sankey Studio: Feature Specification (Design Stage)

## Overview

Sankey Studio lets a feuser build a Sankey diagram (a directed, weighted flow chart) out of their own Tags, Categories, and Projects, then generate it against their real expense data. Unlike the classic income-statement Sankey (money literally moving between accounts), Comaney's underlying data is a flat set of co-occurring labels on a single expense (one category, zero-to-many tags, an optional project), so the tool has to define its own rules for what "a flow from node A to node B" means and how its weight is computed. This document is the settled design, plus what's still open.

---

## Terminology

- **Node**: a Tag, Category, or Project belonging to the feuser; all three types are thrown into a single pool of nodes. A node has a name (from the underlying entity) and a color (cosmetic only, not part of the data model).
- **Edge**: a directed connection the user draws between two nodes in the graph.
- **Graph** (a.k.a. "the node graph"): the user's saved arrangement of nodes, edges, positions, and priorities. One graph per feuser, stored on their own row, not a collection of independently named diagrams.
- **Root**: a node with zero incoming edges.
- **Leaf**: a node with zero outgoing edges.
- **Priority**: a single integer owned by the node itself (not per-edge, not per-parent), used to rank it among whichever siblings it happens to compete with under any given parent.
- **Connector**: an explicit, user-placed passthrough/junction node with no meaning of its own, used to collapse an M-to-N fan-in/fan-out into M+N edges through one shared hub instead of M*N direct edges. As a child, it's always evaluated last and claims whatever its siblings didn't (it has no expense data of its own to match against).
- **Generate**: the explicit action that computes real weights from expense data and renders a chart snapshot from the current graph.

---

## Node pool and placement

Every Tag, Category, and Project visible to the feuser is a potential node. At any time, a node is in exactly one of these states:

1. **Placed**: on the canvas, part of the graph.
2. **Unplaced**: exists in the catalog, not yet added to the canvas. Shown in a sidebar palette.
3. **Disabled**: explicitly excluded via a checkbox on the node, deliberately left out of generation.

Nodes are never created inside Sankey Studio. A new Tag/Category/Project is created through its normal flow elsewhere in the app and simply appears in the "unplaced" palette afterward. Nothing is auto-inserted or auto-wired into the graph. This is also how the graph is meant to be extended over time (e.g. a new vacation, a new Project) without rebuilding from scratch: create the entity as usual, then drag it in from the palette and wire it up.

If a tag/category/project referenced by a placed node is later deleted or archived, what happens to that node is an **open question** (see below).

---

## Editor UX

- A custom canvas/SVG-based node-link editor (pan, zoom, drag-to-place, drag-to-wire). No existing library in the stack covers this; must be built and bundled locally per the asset rules (no CDN).
- **Scroll target decides meaning**: scrolling while hovering over a node adjusts that node's priority number. Scrolling over empty canvas zooms the canvas in/out.
- A **number input field** on each node is the precise/accessible alternative to scroll-to-set-priority.
- A node's disabled checkbox lives on the node itself in the editor.
- The user may explicitly place and wire their own Connector node under any parent as a fan-in/fan-out shortcut (see Connector semantics below); it's drawn as a small diamond, not a box, since it has no settings of its own.

---

## Direction and cycles

- All edges are directed.
- The graph must be a **DAG**: no cycles, enforced live in the editor (an edge that would create a path back to one of its own ancestors is rejected at draw time).
- The graph is explicitly **not required to be a tree**: a node may have multiple parents and multiple children (e.g. "Grocers" fed both directly from "Income" and via "Beach Week 2026"). This is a deliberate allowance, not an edge case to design around; Comaney's own data model already permits an expense to carry a category, several tags, and a project at once, so the chart must be able to represent that.

---

## Priority and the routing algorithm

This is the core computation model, and the reason it looks the way it does: independent pairwise sums per edge (e.g. summing `category=X AND tag=Y` for every edge separately) were considered first, but they break conservation the moment a node has two children whose labels can both match the same expense (double-counted inflow). The model below avoids that by construction.

1. **Priority is global per node**, a single integer, settable by scroll (in the editor) or a number input. It is used purely to sort whatever children a given parent has - **higher number is evaluated first**, so a more specific/important sibling should outrank the broader one it needs to intercept overlapping expenses from.
2. **Tie-break** when two siblings share a priority number: first by origin type, project > category > tag; then alphabetically by name.
3. **Computation is a top-down, first-match-wins partition**, not independent per-edge sums:
   - **Root nodes** (no parent) seed their own distributable total from their real intrinsic value: the sum of feuser-visible expense value carrying that node's label, scoped by the chosen date range and individual/shared mode (see Scoping below).
   - At any node with at least one outgoing edge, walk its children in priority order. Each expense reaching this node is assigned **in full** to the first child (in priority order) whose label it also matches, then stops being considered for that node's other children. If it matches none of the wired children, it simply stays at the node - there is no catch-all it's forced into.
   - A non-root node's inflow is simply the sum of whatever its parent(s) already routed to it in their own partition step. It is never independently recomputed from raw expense data. This is what makes a multi-parent node (like Grocers, fed by both Income and Beach Week 2026) safe: each parent already claimed a disjoint subset of expenses before handing anything downstream, so summing across parents never double-counts.
4. **Conservation is not enforced.** A node's own total is always its full inflow, computed before any distribution to its children, regardless of whether all, some, or none of it gets claimed downstream. `sum(inflow) == sum(outflow)` only happens to hold when a node's wired children collectively cover its whole inflow; it isn't required. This is deliberate: one mechanism now covers a node keeping all of its own money (nothing wired out of it matches), passing all of it along (its children between them claim everything), or keeping some and passing some, without the user needing a different setting for each case.

### Worked example

```
Income total: 2000
  -> Beach Week 2026 (matches project, priority 2): claims 600
     -> Grocers (matches tag, priority 1 under Beach Week): claims 100
     -> (remaining 500 stays at Beach Week itself)
  -> Grocers (direct, priority 1 under Income): claims 300 of the remaining 1400
  -> (remaining 1100 stays at Income itself)

Grocers total inflow = 100 (via Beach Week) + 300 (direct from Income) = 400
```

No expense is counted twice: Beach Week's 600 was removed from Income's pool before the direct Grocers edge ever looked at what remained.

---

## Connector node semantics

- A Connector is an explicit, user-placed node only - nothing is ever auto-injected into a graph.
- As a *child*, a Connector is always evaluated last among its siblings (regardless of its own priority number) and claims whatever they didn't, since it has no expense data of its own to match against.
- As a *parent*, a Connector behaves like any other node: it keeps whatever its own wired children don't claim, the same as a Tag/Category/Project node would.

---

## Rendering rules

- An edge (or a whole downstream sub-branch, if nothing flows into it) with a computed weight of **0 is omitted from the rendered chart**. This only affects the generated output, never the stored graph definition; a branch can disappear from one generated chart (e.g. an empty date range) and reappear in the next without the user having touched the editor.

---

## Scoping controls (reused, not reinvented)

Reuses the existing date-range and mode widgets/backend logic already used by the dashboard and expense list:

- **Date range**: current week / month / year, or a custom min/max range.
- **Mode**:
  - **Individual**: only the feuser's own expenses, counted at full value. Answers "where did my money go."
  - **Shared**: the feuser's own expenses counted at their own `BuddySpending` share (not full value), plus buddies'/participants' expenses counted at the feuser's own share of those. Answers "where did our household budget go."

Both controls scope which expenses are visible to the routing algorithm at generation time.

---

## Generation model (two-step, snapshot-based)

1. **Define**: the user edits the abstract node/edge graph (structure, priorities, placements, disabled flags). No values are computed and nothing is previewed live at this stage.
2. **Generate**: the user clicks "Generate". The server runs the routing algorithm above, scoped by the currently selected date range and individual/shared mode, and returns a rendered chart.

The generated chart is a **snapshot**. Editing the graph afterward, or changing the date range/mode, does not retroactively update it; a fresh "Generate" click is required.

### Unplaced nodes at Generate time

Generation never blocks on incomplete placement: any catalog node (Tag, Category, or Project) that isn't placed on the canvas is simply excluded from the graph, the same as an explicitly disabled node. This lets a feuser build the diagram up incrementally and generate along the way, rather than being forced to reach a fully-placed-or-disabled state before seeing any output.

---

## Query engine reuse and consolidation

The "own tags/category if owner, else feuser's own `ExpenseDataOverlay`, never the foreign owner's" visibility rule already exists as composable `Q`-object builders in `budget/query_parser.py`:

- `_tag_q(val, model, feuser)`
- `_cat_q(val, model, feuser)`
- `_project_q(val)` (simpler: a Project is a direct FK, no per-participant overlay concept)

AND-ing two of these together (`Q_nodeA & Q_nodeB`) gives exactly the pairwise co-occurrence filter an edge's routing step needs.

However, per CLAUDE.md, this same visibility rule is currently duplicated across **four** independent shapes that must be kept manually in sync: `_tag_q`/`_cat_q`, `query_parser.visible_tag_titles` (per-expense Python check), `dashboard_cards._compute_chart` (bulk ORM GROUP BY), and `budget/unclassified.py`'s row-builder. **Implementing Sankey Studio should be the point this gets consolidated into one shared primitive, rather than adding a fifth independent copy.**

Left to the implementor: whether a node's matching expense set is fetched by synthesizing a query string through the existing free-text `query_parser.apply_query` engine, or via directly composed `Q` objects / dedicated ORM code. Either is acceptable, as long as the now-shared visibility-rule primitive is reused, not reimplemented again.

Individual/shared value-scoping (full `Expense.value` vs. `BuddySpending.share_amount`) is a separate, orthogonal concern from tag/category visibility, and must be layered on top of whichever fetch approach is chosen.

---

## Open / deferred questions

Not yet decided; needs an answer before or during implementation:

1. **Dangling nodes**: when a placed node's underlying Tag/Category/Project is deleted or archived, does the node (and its edges) auto-remove from the saved graph, or does it stay as a dangling/greyed-out node until the user manually removes it?
2. **Visual design**: node/edge styling, canvas grid, color picker for nodes, general look and feel.
3. **Accessibility**: a keyboard-driven alternative to scroll-to-set-priority, beyond the number input field.
4. **Snapshot history**: is each "Generate" a throwaway render, or are past generations kept/listable?
5. ~~Whether a node's color is freely chosen per node, or defaults to some existing per-tag/category/project color concept if one exists elsewhere in the app.~~ Resolved: a node defaults to a fixed per-type color but can be freely overridden via a preset-swatches-plus-hex color picker (see `build/js/sankey_editor.js::_openColorPicker`); the override is a plain field on the node, already flowing through save/load/generate with no separate data model.
