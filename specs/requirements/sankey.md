# Sankey Studio

Sources: former `sankey-studio-spec.md`, `budget/sankey_service.py`,
`budget/sankey_generation.py`, `budget/views/sankey.py`, `build/js/sankey_editor.js`,
docs `user-manual/sankey-studio.md`, AGENTS.md.

## Access

### Early access gate
`req~sankey.gate~1`

While a feuser has early access off, the system shall hide the Sankey Studio link, redirect the page to the dashboard and answer its save and generate endpoints with not found.

Covers:
- `feat~sankey~1`

## Graph model

### One graph per feuser
`req~sankey.graph.single~1`

The system shall store one Sankey graph per feuser holding nodes (with position, priority, disabled flag, colour) and directed edges (with optional shaping anchors).

Covers:
- `feat~sankey~1`

### Node pool
`req~sankey.graph.nodes~1`

Every tag, category and project of the feuser shall be a potential node, either placed on the canvas or listed in the Unplaced palette; Sankey Studio shall never create, rename or delete catalog entries.

Covers:
- `feat~sankey~1`

### New entities
`req~sankey.graph.new-entities~1`

When a tag, category or project is created elsewhere, the system shall list it as unplaced and never insert or wire it automatically.

Covers:
- `feat~sankey~1`

### Dangling nodes
`req~sankey.graph.dangling~1`

When the tag, category or project behind a placed node is deleted, or the project is archived or left, the editor and generation shall silently drop that node and its edges.

Covers:
- `feat~sankey~1`

### Connector nodes
`req~sankey.graph.connector~1`

The system shall let the feuser add any number of connector nodes, drawn as small diamonds with two sockets, a colour swatch and a remove button, without priority or disabled settings.

Covers:
- `feat~sankey~1`

### Acyclic graph
`req~sankey.graph.dag~1`

If an edge would create a cycle, then the system shall reject it while drawing and refuse to save or generate a graph containing one.

Covers:
- `feat~sankey~1`

### Impossible edges
`req~sankey.graph.impossible~1`

If an edge leads to a category or project node whose identity is not in the set of categories or projects its source's inflow is already restricted to (directly or through any chain of connectors and tags), then the system shall reject the edge with an explanation at draw time, on save and on generate.

Rationale:
An expense has only one category and one project, so such an edge can never carry money.

Covers:
- `feat~sankey~1`

## Routing

### Root inflow
`req~sankey.route.root~1`

The system shall seed every enabled root node with the value of all in-scope expenses carrying its label.

Covers:
- `feat~sankey~1`

### First match wins
`req~sankey.route.partition~1`

At each node, the system shall pass every expense reaching it in full to the first child, by priority order, whose label it carries, and keep it at the node if no child matches.

Covers:
- `feat~sankey~1`

### Sibling order
`req~sankey.route.order~1`

The system shall order siblings by descending priority, then by type (project, category, tag), then alphabetically, with connector children always last.

Covers:
- `feat~sankey~1`

### Connector routing
`req~sankey.route.connector~1`

A connector child shall receive everything its siblings did not claim and, as a parent, route like any other node.

Covers:
- `feat~sankey~1`

### Multi-parent inflow
`req~sankey.route.multi-parent~1`

The inflow of a non-root node shall be the sum of what its parents routed to it, never recomputed from raw data, so no expense is counted twice.

Covers:
- `feat~sankey~1`

### Node totals
`req~sankey.route.totals~1`

The system shall report each node's full inflow as its value, regardless of how much of it children claim.

Covers:
- `feat~sankey~1`

### Visibility rule
`req~sankey.route.visibility~1`

The system shall match nodes by exact ID against the feuser's own category and tags for own expenses and their overlay for foreign expenses.

Covers:
- `feat~sankey~1`

### Scope
`req~sankey.route.scope~1`

The system shall route only expenses of type Expense within the selected date range, at full value in Personal mode and at the feuser's share in Shared mode.

Covers:
- `feat~sankey~1`

### Excluded nodes
`req~sankey.route.excluded~1`

The system shall leave unplaced and disabled nodes out of generation without blocking it.

Covers:
- `feat~sankey~1`

## Generation and chart

### Explicit generation
`req~sankey.generate.explicit~1`

The system shall compute a chart only when the feuser clicks Generate; later edits to the graph, range or mode shall not change an already generated chart.

Covers:
- `feat~sankey~1`

### Zero pruning
`req~sankey.generate.prune~1`

The generated chart shall omit zero-weight edges and nodes without changing the saved graph.

Covers:
- `feat~sankey~1`

### Isolated nodes
`req~sankey.generate.isolated~1`

The chart shall show nodes with value but no edges as proportional bars below the flow diagram.

Covers:
- `feat~sankey~1`

### True node sizes
`req~sankey.generate.fixed-value~1`

The chart shall size every node by its computed value, also when it routes only part of it onward.

Covers:
- `feat~sankey~1`

### Chart styling
`req~sankey.generate.style~1`

The chart shall colour each link like its target node, hide connector labels, size its height to the most crowded rendered column, and show exact amounts in a hover tooltip.

Covers:
- `feat~sankey~1`

Tags: UI

### Render errors
`req~sankey.generate.errors~1`

If rendering fails, then the page shall show an inline error instead of a blank chart.

Covers:
- `feat~sankey~1`

## Editor

### Save and reset
`req~sankey.editor.save~1`

The editor shall persist the graph only on Save; Reset shall clear all nodes and edges after confirmation, still unsaved.

Covers:
- `feat~sankey~1`

### Wiring
`req~sankey.editor.wiring~1`

The editor shall create an edge by dragging from a node's input or output socket onto another node, with a live line following the cursor and automatic panning while the cursor is near the viewport edge.

Covers:
- `feat~sankey~1`

Tags: UI

### Node controls
`req~sankey.editor.node~1`

Each tag, category or project node shall show a coloured header and rows for priority (number input), disabled checkbox and colour, and a button returning it to the palette.

Covers:
- `feat~sankey~1`

Tags: UI

### Colour picker
`req~sankey.editor.colour~1`

The colour picker shall offer 32 preset swatches and a hex field.

Covers:
- `feat~sankey~1`

Tags: UI

### Edge anchors
`req~sankey.editor.anchors~1`

Right-clicking an edge shall insert a draggable anchor at the nearest segment; left-clicking an anchor shall delete it, left-clicking elsewhere on the edge shall delete the edge; edges shall be drawn as smooth curves through their anchors; anchors shall not affect routing.

Covers:
- `feat~sankey~1`

Tags: UI

### Navigation
`req~sankey.editor.navigation~1`

The canvas shall zoom around the cursor proportionally to wheel distance, zoom with buttons around its centre, pan without limits by dragging empty space, and never select text while panning.

Covers:
- `feat~sankey~1`

Tags: UI

### Snap to grid
`req~sankey.editor.snap~1`

While "Snap to grid" is on (default), dragged nodes and anchors shall snap to the grid; toggling it shall never move anything already placed.

Covers:
- `feat~sankey~1`

Tags: UI

### Spawn position
`req~sankey.editor.spawn~1`

Newly placed nodes shall appear inside the current viewport.

Covers:
- `feat~sankey~1`

Tags: UI

### Export
`req~sankey.export~1`

The account export shall include the saved graph as `sankey_graph.json` when one exists.

Covers:
- `feat~sankey~1`
