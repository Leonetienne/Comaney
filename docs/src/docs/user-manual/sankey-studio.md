# Sankey Studio

Sankey Studio is an early access feature. To see it in your sidebar, turn on **Enable early access features** in [Account & Settings](account-settings.md#early-access) first.

Sankey Studio lets you build a flow diagram out of your own Categories, Tags, and Projects, then generate it from your real expenses to see how your money actually moves between them.

## What does it show?

A Sankey diagram is a chart made of boxes ("nodes") connected by arrows ("flows"). The thicker an arrow, the more money flows along it. You decide which of your Categories, Tags, and Projects should connect to which; Sankey Studio then fills in the numbers from your real spending.

Sankey Studio only ever looks at your **expenses** - regular spending. It never includes income, and it never includes money moved to or from savings, even if that transaction happens to carry a Category, Tag, or Project that's on your diagram. So when placing nodes, only use Categories and Tags you actually use on expenses; one you only ever use on income will always show as empty here, since nothing it's on ever counts.

## How to read it

Follow a box from left to right. Each arrow leaving a box represents a slice of that box's money going somewhere more specific. A box that has money entering it but nothing wired out (or only some of its money claimed by what is wired out) simply keeps the rest for itself - there's no "leftover" bucket to worry about; it's just shown sitting on the node.

The further right a node sits in a chain, the stricter its requirements are. Think of each connection as adding one more condition: money that reaches a node two steps in has already had to match the first node's condition *and* the second one's. So a node several steps to the right represents a narrower and narrower slice of your spending, since it can only ever hold money that already qualified for everything upstream of it. This is why an edge from one Category node to a *different* Category node (or one Project to a different Project) is never allowed: an expense only ever has one Category and one Project, so it can never satisfy two different ones at once. Tags don't have this restriction, since one expense can carry several tags at the same time.

Hover over any box or arrow in a generated chart to see its exact amount. Arrows are colored to match the box they're flowing into, so you can follow a color across the diagram to see where money ends up.

## Building your diagram

Every Category, Tag, and Project you have shows up in the **Unplaced** panel above the canvas. Click one to add it to the canvas.

Once a node is on the canvas, it shows its own little property list, same idea as a header with a couple of settings underneath:

- **Drag** its header or body to reposition it.
- **Connect** it to another node by dragging from the small dot on its left edge (incoming) or right edge (outgoing) to another node's dot; a line follows your cursor while you drag, and letting go over another node completes the connection. If the node you're connecting to is off-screen, just drag toward the edge of the canvas and it'll pan on its own to follow you there.
- **Set its priority** by typing a number directly into its Priority field. If two nodes downstream of the same node could both apply to the same expense, the one with the higher number wins and claims that expense first; the other only gets what's left. Give the more specific node (e.g. a "Vacation" node that should catch vacation-related restaurant spending before a general "Restaurants" node does) the higher number.
- **Disable** it with its Disabled checkbox if you'd rather leave it out of the diagram entirely without removing it from the canvas.
- **Pick a color** by clicking its Color swatch: choose from 32 preset colors, or type your own hex code (e.g. `#e15759`).
- **Remove** it from the canvas with its × button, sending it back to Unplaced.

A node doesn't have to fully account for its money. If some of what reaches a node doesn't match anything you've wired out of it, that part just stays with the node itself instead of disappearing or needing anywhere special to go - so a node can keep all of its own money (nothing it's connected to matches), pass all of it along (everything matches something), or keep part and pass part along. This is automatic; there's nothing to turn on.

Scroll on empty canvas space (not on a node) to zoom in and out, centered on wherever your cursor is. The panel in the top-right corner of the canvas has everything else you need while building: **+ Connector node**, **Save**, **Reset**, a **Snap to grid** checkbox, and the **−**/**+** zoom buttons. Click and drag on empty canvas space to pan around; there's no limit to how far you can move it.

**Snap to grid** is on by default to make it easier to line things up neatly: while it's checked, any node (or shaping anchor, see below) you drag snaps to the nearest grid line as you drop it. Uncheck it if you'd rather place things freely. Either way, it only affects things while you're actively moving them - toggling it never shifts anything already placed.

Made a mess, or just want a clean slate? **Reset** clears every node and edge from the canvas after you confirm. Like everything else here, this doesn't touch your saved diagram until you click Save afterward.

### Shaping a connection

A straight line between two nodes can be hard to follow once your diagram gets busy. Right-click anywhere on a connection to drop a small diamond-shaped **anchor** onto it, then drag the anchor to bend the line wherever makes the diagram easiest to read. Anchors are purely visual - they don't change what's connected to what, or affect any of the numbers.

- **Left-click** an anchor to delete just that anchor; left-click anywhere else on the line to delete the whole connection (including any anchors on it).
- **Right-click** an existing anchor does nothing - only a right-click on a plain stretch of line adds a new one.
- Hovering a connection or an anchor shows a small reminder of what each click does, and turns the anchor red to show what a left-click there would remove.

### Connector nodes

If you're connecting a handful of nodes to a bunch of others (say, 5 categories that should all fan out into the same 8 tags), wiring every pair directly gets tedious fast. **+ Connector node** adds a plain junction you can use as a shortcut: wire your 5 categories into the connector, then wire the connector out to your 8 tags, instead of drawing all 40 direct connections.

A connector doesn't represent anything of its own - it has no money of its own to match against, no Priority field, and no Disabled checkbox (it's always active). It just passes along whatever reaches it: money simply flows through it on its way from one side to the other, exactly as if it wasn't there. Because it isn't a "real" node, it's drawn as a small diamond instead of a box - just its color swatch, its two connection dots, and a small × to remove it. In the finished chart, a connector's own bar is shown with no name label on it - hover over it if you want to see its total.

### No loops allowed, and some connections just can't carry money

Flows must all point the same general direction; Sankey Studio won't let you connect things in a circle.

A Category (and a Project) can only ever be one specific value for a given expense, never two at once. So connecting one Category node straight into a *different* Category node (or one Project into a different Project) can never carry any money; either one of them would have to be labeled as both values on the same expense, which isn't possible. This isn't just about two Category nodes wired directly to each other, either - it's still true if a Connector, or even a Tag, sits in between them (see "How to read it" above). Sankey Studio rejects that connection with an explanation rather than letting you build a diagram that silently shows nothing. Tags don't have this restriction, since one expense can carry several tags at once.

## Saving and generating

Your diagram (the boxes and arrows) is saved separately from the numbers. Click **Save** any time to keep your layout. Click **Generate**, below the canvas, to calculate real numbers from your expenses for the currently selected date range and mode, and draw the chart.

Changing the date range, the mode, or the diagram itself won't update an already-generated chart; click **Generate** again whenever you want a fresh one.

You don't need to place every Category, Tag, and Project before generating - anything you haven't placed yet is simply left out of the chart, the same as if you'd disabled it. This lets you build the diagram up gradually and generate along the way.

## Personal vs. shared

Just like the Dashboard and Expenses page, you can switch between:

- **Personal**: only your own expenses, counted in full.
- **Shared**: your own expenses counted at your share, plus your share of anything you split with buddies or in a project.

Use the same date range control at the top to choose which period the diagram covers.

Sankey Studio only ever counts your actual spending. Income and money moved to or from savings are never included, even if they carry a Category, Tag, or Project that's placed on your diagram.
