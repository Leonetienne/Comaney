import Alpine from 'alpinejs';
import { sankey as d3sankey, sankeyLinkHorizontal } from 'd3-sankey';
import dateRange from './date-range.js';

window._dateRange = dateRange;

// The "Display mode" (Personal/Shared) toggle lives in the shared
// partials/_date_range_nav.html partial via Alpine's $store.sharing, same
// as the dashboard/expenses pages. Those pages each bring their own Alpine
// + register the store; this page needs to do the same or the toggle's
// @click handlers simply never fire (Alpine never processes the markup).
document.addEventListener('alpine:init', () => {
    Alpine.store('sharing', {
        mode: localStorage.getItem('sharingMode') || 'personal',
        set(mode) {
            this.mode = mode;
            localStorage.setItem('sharingMode', mode);
        },
    });
});
Alpine.start();

const SVG_NS = 'http://www.w3.org/2000/svg';
const NODE_W = 200;
const HEADER_H = 26;
const ROW_H = 24;
const SOCKET_R = 6;
// A Connector is pure wiring with no meaning of its own -- so it's drawn
// as a small unlabeled diamond instead of the usual property box: no
// header, no title, no Priority/Disabled rows. Its priority is always 0
// (irrelevant anyway: as a child, a Connector is always evaluated last
// regardless of its own priority number, see build_children_order) and it
// can never be disabled.
const CONNECTOR_SIZE = 36;
const ZOOM_MIN = 0.3;
const ZOOM_MAX = 2.5;
const ZOOM_BUTTON_FACTOR = 1.2;
// Wheel deltaY magnitude varies wildly by device (a trackpad fires many
// small events per gesture, a mouse wheel fires few large ones); scaling
// the zoom factor by the actual deltaY, rather than applying a fixed step
// per event, keeps a small trackpad nudge small and a big scroll big.
const ZOOM_WHEEL_SENSITIVITY = 0.0015;
const TYPE_LABEL = { tag: 'Tag', category: 'Category', project: 'Project', connector: 'Connector' };
const DEFAULT_COLORS = {
    tag: '#59a14f', category: '#4e79a7', project: '#f28e2b', connector: '#5b8fb0',
};
// Snap-to-grid only affects a node/anchor while it's actively being
// dragged -- toggling the checkbox never retroactively moves anything
// already placed (see _applySnap).
const GRID_SIZE = 20;
// An anchor is a small diamond (a rotated square) sitting on an edge purely
// for visual line-shaping -- see _drawAnchor. Half-size used as the polygon
// radius.
const ANCHOR_SIZE = 10;
// 8 base hues (a validated CVD-safe categorical order), each with 3 tone
// variants (lighter tint, darker shade, darkest shade) for 32 total --
// grouped in fours so each hue's family sits together in the popover grid.
// While dragging a new connection, the cursor nearing the viewport's edge
// auto-pans the canvas so a node far outside the current view can still be
// reached without letting go and panning manually first. Distance in
// screen px from the edge that triggers panning, and the pan speed (in
// screen px/frame) at maximum proximity, tapering to 0 at EDGE distance.
const AUTO_PAN_EDGE = 60;
const AUTO_PAN_SPEED = 16;
const COLOR_PRESETS = [
    '#2a78d6', '#75a7e4', '#1d5496', '#133660', // blue
    '#1baf7a', '#6bcba9', '#137a55', '#0c4f37', // aqua
    '#eda100', '#f3c259', '#a67100', '#6b4800', // yellow
    '#008300', '#59ae59', '#005c00', '#003b00', // green
    '#4a3aa7', '#897fc6', '#342975', '#211a4b', // violet
    '#e34948', '#ed8988', '#9f3332', '#662120', // red
    '#e87ba4', '#f0a9c4', '#a25673', '#68374a', // magenta
    '#eb6834', '#f29d7b', '#a44924', '#6a2f17', // orange
];
// A Connector is always the lowest-priority catch-all child of any parent
// it's wired under (see budget/sankey_service.py's module docstring), and
// -- since it has no expense data of its own to match against -- always
// claims whatever its siblings didn't when it's used as a child.
const CATCH_ALL_TYPES = new Set(['connector']);
// An expense's category (or project) is always exactly one value, so an
// edge between two *different* nodes of the same one of these types can
// never have a matching expense on both ends -- mirrors
// budget/sankey_service.py::is_impossible_edge.
const MUTUALLY_EXCLUSIVE_TYPES = new Set(['category', 'project']);

function el(tag, attrs, ns) {
    const e = document.createElementNS(ns || SVG_NS, tag);
    for (const k in (attrs || {})) e.setAttribute(k, attrs[k]);
    return e;
}

function uid() {
    return Math.random().toString(36).slice(2, 10);
}

// Mirrors budget/sankey_service.py::parse_node_key: 'tag:3' -> ['tag', '3'].
function parseNodeKey(key) {
    const idx = key.indexOf(':');
    return idx === -1 ? [key, ''] : [key.slice(0, idx), key.slice(idx + 1)];
}

class SankeyEditor {
    constructor(cfg) {
        this.csrf = cfg.csrf;
        this.urls = cfg.urls;
        this.catalog = cfg.catalog;      // key -> {type, title}
        this.nodes = cfg.nodes;          // key -> {x,y,priority,disabled,color,label}
        this.edges = cfg.edges;          // [{source,target}]
        this.chart = null;
        this.error = '';
        this.zoom = 1;
        this.pan = { x: 0, y: 0 };
        this.snapToGrid = true;
        this._connecting = null;         // {key, endpoint: 'input'|'output'}
        this._tempLine = null;
        this._drag = null;
        this._anchorDrag = null;         // {edge, idx, offsetX, offsetY}
        this._panDrag = null;
        this._colorPopover = null;
        this._colorPopoverOutsideHandler = null;
        this.tooltipEl = null;
        this._lastMouseScreenPos = null;
        this._autoPanRAF = null;

        this.root = document.getElementById('sankey-root');
        this._build();
        this.render();
    }

    // ── DOM scaffold ─────────────────────────────────────────────────────
    _build() {
        this.root.innerHTML = `
            <div class="sankey-hint-bar">
                <div class="sankey-hint">
                    <div>Scroll the canvas to zoom.</div>
                    <div>Click-drag empty canvas to pan.</div>
                    <div>Drag from a socket to wire it to another node.</div>
                    <div>Right-click a connection to add a shaping anchor; left-click a connection or anchor to delete it.</div>
                </div>
            </div>
            <p class="sankey-error" id="sankey-error" style="display:none"></p>
            <div class="sankey-palette" id="sankey-palette"></div>
            <div class="sankey-canvas-wrap" id="sankey-canvas-wrap">
                <svg id="sankey-canvas" width="100%" height="720"></svg>
                <!-- The in-canvas control panel ("the toolbar"): graph-editing
                     actions live next to the thing they act on, the same way
                     the zoom +/- buttons already did. -->
                <div class="sankey-canvas-toolbar" id="sankey-canvas-toolbar">
                    <button type="button" class="btn btn-secondary sankey-toolbar-btn" id="sankey-add-connector">+ Connector node</button>
                    <button type="button" class="btn btn-secondary sankey-toolbar-btn" id="sankey-save">Save</button>
                    <button type="button" class="btn btn-secondary sankey-toolbar-btn" id="sankey-reset">Reset</button>
                    <label class="sankey-snap-toggle">
                        <input type="checkbox" id="sankey-snap-grid" checked> Snap to grid
                    </label>
                    <div class="sankey-zoom-group">
                        <button type="button" class="btn btn-secondary sankey-zoom-btn" id="sankey-zoom-out" title="Zoom out">−</button>
                        <button type="button" class="btn btn-secondary sankey-zoom-btn" id="sankey-zoom-in" title="Zoom in">+</button>
                    </div>
                </div>
            </div>
            <button type="button" class="btn btn-primary sankey-generate-btn" id="sankey-generate">Generate</button>
            <div class="sankey-chart-wrap" id="sankey-chart-wrap" style="display:none">
                <h3>Generated chart</h3>
                <svg id="sankey-chart" width="100%" height="500"></svg>
            </div>
        `;
        this.svg = this.root.querySelector('#sankey-canvas');
        this.canvasWrap = this.root.querySelector('#sankey-canvas-wrap');
        this.paletteEl = this.root.querySelector('#sankey-palette');
        this.errorEl = this.root.querySelector('#sankey-error');
        this.chartWrap = this.root.querySelector('#sankey-chart-wrap');
        this.chartSvg = this.root.querySelector('#sankey-chart');

        this.g = el('g', { id: 'sankey-g' });
        this.svg.appendChild(this.g);

        this.root.querySelector('#sankey-add-connector').addEventListener('click', () => this._addPassthrough());
        this.root.querySelector('#sankey-reset').addEventListener('click', () => this.reset());
        this.root.querySelector('#sankey-save').addEventListener('click', () => this.save());
        this.root.querySelector('#sankey-generate').addEventListener('click', () => this.generate());
        this.root.querySelector('#sankey-zoom-in').addEventListener('click', () => this._zoomBy(ZOOM_BUTTON_FACTOR));
        this.root.querySelector('#sankey-zoom-out').addEventListener('click', () => this._zoomBy(1 / ZOOM_BUTTON_FACTOR));
        this.root.querySelector('#sankey-snap-grid').addEventListener('change', (e) => {
            this.snapToGrid = e.target.checked;
        });

        this.svg.addEventListener('wheel', (e) => this._onCanvasWheel(e), { passive: false });
        this.svg.addEventListener('mousedown', (e) => this._startPan(e));
        this.svg.addEventListener('mousemove', (e) => this._onMouseMove(e));
        this.svg.addEventListener('mouseup', () => { this._endDrag(); this._endConnect(); this._endPan(); });
        this.svg.addEventListener('mouseleave', () => { this._endDrag(); this._endConnect(); this._endPan(); });

        this.tooltipEl = document.createElement('div');
        this.tooltipEl.id = 'sankey-tooltip';
        this.tooltipEl.className = 'sankey-tooltip';
        this.tooltipEl.style.display = 'none';
        document.body.appendChild(this.tooltipEl);
    }

    _showError(msg) {
        this.error = msg;
        this.errorEl.textContent = msg;
        this.errorEl.style.display = msg ? 'block' : 'none';
    }

    // ── Custom tooltip ───────────────────────────────────────────────────
    // A native SVG <title> only shows up after the browser's own hover
    // delay (roughly a second) -- too slow for a diagram meant to be read
    // quickly. This is a plain fixed-position div that appears immediately
    // on mouseenter and tracks the cursor, used for both the editor
    // (edge/anchor hints) and the generated chart (node/link values).
    _showTooltip(text, evt) {
        this.tooltipEl.textContent = text;
        this.tooltipEl.style.display = 'block';
        this._moveTooltip(evt);
    }

    _moveTooltip(evt) {
        const margin = 14;
        const width = this.tooltipEl.offsetWidth;
        let left = evt.clientX + margin;
        if (left + width > window.innerWidth) {
            left = evt.clientX - margin - width;
        }
        this.tooltipEl.style.left = `${left}px`;
        this.tooltipEl.style.top = `${evt.clientY + 14}px`;
    }

    _hideTooltip() {
        this.tooltipEl.style.display = 'none';
    }

    // ── Node key helpers ─────────────────────────────────────────────────
    _nodeType(key) {
        if (key.startsWith('connector:')) return 'connector';
        return this.catalog[key] ? this.catalog[key].type : 'tag';
    }

    _nodeTitle(key) {
        if (this.nodes[key] && this.nodes[key].label) return this.nodes[key].label;
        if (this.catalog[key]) return this.catalog[key].title;
        return key;
    }

    // HEADER_H + one blank "connector row" (sockets live here, deliberately
    // apart from any labeled/settable row so an edge can never look like it
    // targets a specific property) + one row per actual property (Priority,
    // Disabled, Color). Only ever called for a Tag/Category/Project node --
    // see _drawConnectorNode, which draws a plain diamond with no property
    // rows at all (a Connector is pure wiring, so neither Priority nor
    // Disabled mean anything for it; its color override is a small swatch
    // next to the diamond instead, see _drawConnectorNode).
    _nodeHeight() {
        return HEADER_H + ROW_H + ROW_H * 3;
    }

    _placedKeys() {
        return Object.keys(this.nodes);
    }

    _unplacedKeys() {
        return Object.keys(this.catalog).filter((k) => !(k in this.nodes));
    }

    // ── Palette (full-width bar above the canvas) ───────────────────────
    _renderPalette() {
        const unplaced = this._unplacedKeys();
        const groups = { project: [], category: [], tag: [] };
        unplaced.forEach((k) => groups[this.catalog[k].type].push(k));

        let html = '<h4>Unplaced</h4>';
        if (unplaced.length === 0) html += '<p class="sankey-palette-empty">Everything is placed.</p>';
        html += '<div class="sankey-palette-groups">';
        ['project', 'category', 'tag'].forEach((t) => {
            if (!groups[t].length) return;
            html += `<div class="sankey-palette-group"><span class="sankey-palette-group-label">${TYPE_LABEL[t]}s</span><div class="sankey-palette-chips">`;
            groups[t].forEach((k) => {
                html += `<button type="button" class="sankey-palette-item" data-key="${k}">+ ${this.catalog[k].title}</button>`;
            });
            html += '</div></div>';
        });
        html += '</div>';
        this.paletteEl.innerHTML = html;
        this.paletteEl.querySelectorAll('.sankey-palette-item').forEach((btn) => {
            btn.addEventListener('click', () => this._place(btn.dataset.key));
        });
    }

    // World-space rect of whatever's currently visible in the canvas
    // viewport, given the current pan/zoom.
    _viewportWorldRect() {
        const w = this.svg.clientWidth || 800;
        const h = this.svg.clientHeight || 600;
        return {
            x0: -this.pan.x / this.zoom,
            y0: -this.pan.y / this.zoom,
            w: w / this.zoom,
            h: h / this.zoom,
        };
    }

    // A newly added node spawns somewhere inside the currently visible
    // viewport (a small grid sized to fit it, wrapping so repeated adds
    // don't all land in the exact same spot) rather than at a fixed
    // canvas-origin position that can be far outside the visible area once
    // the user has panned/zoomed around a large diagram.
    _nextSpawnPos() {
        const margin = 30;
        const rect = this._viewportWorldRect();
        const cols = Math.max(1, Math.floor((rect.w - margin * 2) / (NODE_W + 50)));
        const rows = Math.max(1, Math.floor((rect.h - margin * 2) / 130));
        const perPage = cols * rows;
        const count = this._placedKeys().length;
        const slot = count % perPage;
        // Once a zoomed-in viewport's grid runs out of slots, further adds
        // would otherwise repeat the exact same positions forever (landing
        // exactly on top of earlier nodes); stagger each lap with a small
        // diagonal offset instead, the same idea as a window manager
        // cascading new windows.
        const cascade = (Math.floor(count / perPage) % 5) * 24;
        return {
            x: rect.x0 + margin + (slot % cols) * (NODE_W + 50) + cascade,
            y: rect.y0 + margin + Math.floor(slot / cols) * 130 + cascade,
        };
    }

    _place(key) {
        const pos = this._nextSpawnPos();
        this.nodes[key] = {
            x: pos.x,
            y: pos.y,
            priority: 0,
            disabled: false,
            color: DEFAULT_COLORS[this._nodeType(key)],
        };
        this.render();
    }

    // Adds a new Connector node (a plain wiring shortcut with no meaning
    // of its own -- see the CATCH_ALL_TYPES/module-level note above).
    _addPassthrough() {
        const key = `connector:${uid()}`;
        const pos = this._nextSpawnPos();
        this.nodes[key] = {
            x: pos.x,
            y: pos.y,
            priority: 0,
            disabled: false,
            color: DEFAULT_COLORS.connector,
            label: TYPE_LABEL.connector,
        };
        this.render();
    }

    _removeNode(key) {
        delete this.nodes[key];
        this.edges = this.edges.filter((e) => e.source !== key && e.target !== key);
        this.render();
    }

    // ── Color override popover ───────────────────────────────────────────
    // A small floating panel (preset swatches + a hex field) anchored at
    // the clicked swatch's screen position, closing on an outside click.
    // `n.color` is a plain field on the node -- already saved/loaded as
    // part of config_json and already read back by the generated chart
    // (see budget/sankey_generation.py's nodes_out), so no backend change
    // is needed to make an override persist and take effect.
    _openColorPicker(key, screenX, screenY) {
        this._closeColorPicker();
        const n = this.nodes[key];
        const popover = document.createElement('div');
        popover.className = 'sankey-color-popover';
        popover.style.left = `${screenX}px`;
        popover.style.top = `${screenY}px`;

        const presetsEl = document.createElement('div');
        presetsEl.className = 'sankey-color-presets';
        COLOR_PRESETS.forEach((c) => {
            const swatch = document.createElement('button');
            swatch.type = 'button';
            swatch.className = 'sankey-color-swatch';
            swatch.style.background = c;
            swatch.addEventListener('click', () => {
                n.color = c;
                this._closeColorPicker();
                this.render();
            });
            presetsEl.appendChild(swatch);
        });
        popover.appendChild(presetsEl);

        const hexInput = document.createElement('input');
        hexInput.type = 'text';
        hexInput.className = 'sankey-color-hex';
        hexInput.placeholder = '#rrggbb';
        hexInput.value = n.color || '';
        const applyHex = () => {
            const v = hexInput.value.trim();
            if (/^#[0-9a-fA-F]{6}$/.test(v)) {
                n.color = v;
                this._closeColorPicker();
                this.render();
            }
        };
        hexInput.addEventListener('keydown', (e) => {
            e.stopPropagation();
            if (e.key === 'Enter') applyHex();
        });
        hexInput.addEventListener('change', applyHex);
        popover.appendChild(hexInput);

        document.body.appendChild(popover);
        this._colorPopover = popover;
        // Deferred so the click that opened the popover doesn't immediately
        // close it again via this same listener.
        setTimeout(() => {
            this._colorPopoverOutsideHandler = (e) => {
                if (!popover.contains(e.target)) this._closeColorPicker();
            };
            document.addEventListener('mousedown', this._colorPopoverOutsideHandler);
        }, 0);
    }

    _closeColorPicker() {
        if (this._colorPopover) {
            this._colorPopover.remove();
            this._colorPopover = null;
        }
        if (this._colorPopoverOutsideHandler) {
            document.removeEventListener('mousedown', this._colorPopoverOutsideHandler);
            this._colorPopoverOutsideHandler = null;
        }
    }

    // Only affects a node/anchor while it's actively being dragged -- see
    // the GRID_SIZE comment; toggling the checkbox never moves anything
    // already placed.
    _applySnap(x, y) {
        if (!this.snapToGrid) return { x, y };
        return { x: Math.round(x / GRID_SIZE) * GRID_SIZE, y: Math.round(y / GRID_SIZE) * GRID_SIZE };
    }

    async reset() {
        try {
            await window.confirmDialog(
                'Clear every node and edge from this diagram? Your saved graph is only affected once you click Save afterward.',
                'Reset',
            );
        } catch (_) {
            return;
        }
        this.nodes = {};
        this.edges = [];
        this.chart = null;
        this.chartWrap.style.display = 'none';
        this._showError('');
        this.render();
    }

    // ── Cycle check (client-side hint only; server re-validates on save) ──
    _wouldCreateCycle(source, target) {
        const adj = {};
        this.edges.concat([{ source, target }]).forEach((e) => {
            (adj[e.source] = adj[e.source] || []).push(e.target);
        });
        const stack = [target];
        const seen = new Set();
        while (stack.length) {
            const n = stack.pop();
            if (n === source) return true;
            if (seen.has(n)) continue;
            seen.add(n);
            (adj[n] || []).forEach((c) => stack.push(c));
        }
        return false;
    }

    // ── Canvas render ────────────────────────────────────────────────────
    // Just the pan/zoom transform, with nothing else touched -- every node
    // and edge is already positioned relative to this.g's own transform,
    // so a pan/zoom change alone never needs a full re-render. Used by the
    // auto-pan loop below, which must NOT call the full render() (that
    // clears this.g's children, which would delete the live temp
    // connecting line mid-drag).
    _applyTransform() {
        this.g.setAttribute('transform', `translate(${this.pan.x},${this.pan.y}) scale(${this.zoom})`);
    }

    render() {
        this._renderPalette();
        this.g.innerHTML = '';
        this._applyTransform();

        // edges first (so nodes draw on top)
        this.edges.forEach((e) => this._drawEdge(e));
        Object.keys(this.nodes).forEach((k) => this._drawNode(k));
    }

    _socketPos(key, endpoint) {
        const n = this.nodes[key];
        if (this._nodeType(key) === 'connector') {
            return { x: n.x + (endpoint === 'output' ? CONNECTOR_SIZE : 0), y: n.y + CONNECTOR_SIZE / 2 };
        }
        // Always the connector row's center, regardless of node height, so
        // a wire never visually lines up with a specific property row.
        return { x: n.x + (endpoint === 'output' ? NODE_W : 0), y: n.y + HEADER_H + ROW_H / 2 };
    }

    _edgePathD(x1, y1, x2, y2) {
        const mx = (x1 + x2) / 2;
        return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
    }

    // Ordered waypoints an edge actually routes through: source socket,
    // then any user-added anchors (in shaping order), then target socket.
    // Anchors are purely visual (see the module-level anchor notes on
    // _drawAnchor) -- they never change what the edge connects.
    _edgeWaypoints(edge) {
        const from = this._socketPos(edge.source, 'output');
        const to = this._socketPos(edge.target, 'input');
        return [from, ...(edge.anchors || []), to];
    }

    // Unit tangent direction at each waypoint: horizontal at the very first
    // and last point (so the curve still leaves/enters each node's socket
    // flat, exactly like the plain 2-point case), and the direction toward
    // the next point averaged with the direction from the previous point
    // for every anchor in between (a standard Catmull-Rom-style tangent),
    // so the curve keeps flowing smoothly through each shaping anchor
    // instead of kinking at it.
    _waypointTangents(points) {
        const n = points.length;
        return points.map((p, i) => {
            if (i === 0 || i === n - 1) return { x: 1, y: 0 };
            const prev = points[i - 1];
            const next = points[i + 1];
            const dx = next.x - prev.x;
            const dy = next.y - prev.y;
            const len = Math.hypot(dx, dy) || 1;
            return { x: dx / len, y: dy / len };
        });
    }

    // A smooth curve through source -> anchors -> target when there's at
    // least one anchor to shape the line with (one cubic Bezier segment
    // per gap, tangent-continuous at every anchor so it never kinks);
    // otherwise the original single smooth curve, unchanged from before
    // anchors existed.
    _edgePathFromPoints(points) {
        if (points.length <= 2) {
            return this._edgePathD(points[0].x, points[0].y, points[1].x, points[1].y);
        }
        const tangents = this._waypointTangents(points);
        let d = `M${points[0].x},${points[0].y}`;
        for (let i = 0; i < points.length - 1; i++) {
            const p0 = points[i];
            const p1 = points[i + 1];
            const segLen = Math.hypot(p1.x - p0.x, p1.y - p0.y);
            const c = segLen / 3;
            const cp1x = p0.x + tangents[i].x * c;
            const cp1y = p0.y + tangents[i].y * c;
            const cp2x = p1.x - tangents[i + 1].x * c;
            const cp2y = p1.y - tangents[i + 1].y * c;
            d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p1.x},${p1.y}`;
        }
        return d;
    }

    _pointToSegmentDistance(px, py, a, b) {
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const lenSq = dx * dx + dy * dy;
        let t = lenSq === 0 ? 0 : ((px - a.x) * dx + (py - a.y) * dy) / lenSq;
        t = Math.max(0, Math.min(1, t));
        const cx = a.x + t * dx;
        const cy = a.y + t * dy;
        return Math.hypot(px - cx, py - cy);
    }

    // Inserts a new anchor at whichever existing segment (source -> first
    // anchor -> ... -> target) the click point is actually closest to, so
    // right-clicking partway along an already-shaped line inserts the new
    // anchor in the right spot rather than always at the end.
    _addAnchorAt(edge, x, y) {
        const points = this._edgeWaypoints(edge);
        let bestIdx = 0;
        let bestDist = Infinity;
        for (let i = 0; i < points.length - 1; i++) {
            const d = this._pointToSegmentDistance(x, y, points[i], points[i + 1]);
            if (d < bestDist) {
                bestDist = d;
                bestIdx = i;
            }
        }
        edge.anchors = edge.anchors || [];
        // points[0] is the source socket (not an anchor), so segment i sits
        // between anchors[i-1] and anchors[i] -- inserting at anchors index
        // i is exactly that gap.
        edge.anchors.splice(bestIdx, 0, { x, y });
    }

    _deleteAnchor(edge, idx) {
        edge.anchors.splice(idx, 1);
    }

    _startAnchorDrag(edge, idx, evt) {
        const pt = this._svgPoint(evt);
        const anchor = edge.anchors[idx];
        this._anchorDrag = {
            edge, idx,
            offsetX: pt.x / this.zoom - this.pan.x / this.zoom - anchor.x,
            offsetY: pt.y / this.zoom - this.pan.y / this.zoom - anchor.y,
        };
    }

    _drawAnchor(edge, idx, group) {
        const anchor = edge.anchors[idx];
        const r = ANCHOR_SIZE / 2;
        const wrapper = el('g', { class: 'sankey-anchor', transform: `translate(${anchor.x},${anchor.y})` });

        const diamond = el('polygon', {
            points: `0,${-r} ${r},0 0,${r} ${-r},0`,
            class: 'sankey-anchor-diamond',
        });
        wrapper.appendChild(diamond);

        wrapper.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            this._startAnchorDrag(edge, idx, e);
        });
        // Left click deletes just this anchor, never the whole edge (the
        // edge's own click handler lives on a sibling <path>, never a
        // descendant of this <g>, so it can't fire from this click).
        wrapper.addEventListener('click', (e) => {
            e.stopPropagation();
            this._deleteAnchor(edge, idx);
            this._hideTooltip();
            this.render();
        });
        // Right click on an anchor does nothing (only a right click on the
        // connection itself, away from any anchor, adds a new one).
        wrapper.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            e.stopPropagation();
        });
        wrapper.addEventListener('mouseenter', (e) => this._showTooltip('Left click: delete anchor · Right click: does nothing', e));
        wrapper.addEventListener('mousemove', (e) => this._moveTooltip(e));
        wrapper.addEventListener('mouseleave', () => this._hideTooltip());

        group.appendChild(wrapper);
    }

    _drawEdge(edge) {
        const s = this.nodes[edge.source];
        const t = this.nodes[edge.target];
        if (!s || !t) return;
        const points = this._edgeWaypoints(edge);
        const group = el('g', { class: 'sankey-edge-group' });

        const path = el('path', {
            d: this._edgePathFromPoints(points),
            class: 'sankey-edge',
            'data-source': edge.source, 'data-target': edge.target,
        });
        // Left click deletes the whole connection (source -> target); an
        // anchor sitting on the line is drawn as its own element on top and
        // handles its own click before this one ever sees it, so this only
        // fires when the click actually lands on plain line, not an anchor.
        path.addEventListener('click', () => {
            this.edges = this.edges.filter((e) => e !== edge);
            this.render();
        });
        // Right click adds a shaping anchor at the click point, unless the
        // click landed on an existing anchor (that's the anchor's own
        // contextmenu handler, which does nothing and stops here).
        path.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            const pt = this._svgPoint(e);
            const worldX = (pt.x - this.pan.x) / this.zoom;
            const worldY = (pt.y - this.pan.y) / this.zoom;
            this._addAnchorAt(edge, worldX, worldY);
            this.render();
        });
        path.addEventListener('mouseenter', (e) => this._showTooltip('Left click: delete connection · Right click: add anchor', e));
        path.addEventListener('mousemove', (e) => this._moveTooltip(e));
        path.addEventListener('mouseleave', () => this._hideTooltip());
        group.appendChild(path);

        (edge.anchors || []).forEach((_, idx) => this._drawAnchor(edge, idx, group));
        this.g.appendChild(group);
    }

    _drawPropRow(group, rowIndex, labelText, makeInput) {
        // +1 row: the blank connector row always comes first, right after the header.
        const y = HEADER_H + ROW_H + rowIndex * ROW_H;
        const rowBg = el('rect', { x: 0, y, width: NODE_W, height: ROW_H, class: 'sankey-node-row' + (rowIndex % 2 ? ' sankey-node-row--alt' : '') });
        group.appendChild(rowBg);

        const label = el('text', { x: 8, y: y + 16, class: 'sankey-node-proprow-label' });
        label.textContent = labelText;
        group.appendChild(label);

        const fo = el('foreignObject', { x: NODE_W - 56, y: y + 3, width: 48, height: ROW_H - 6 });
        const input = makeInput();
        fo.appendChild(input);
        group.appendChild(fo);
    }

    _drawNode(key) {
        if (this._nodeType(key) === 'connector') {
            this._drawConnectorNode(key);
            return;
        }
        const n = this.nodes[key];
        const h = this._nodeHeight();
        const group = el('g', { class: 'sankey-node' + (n.disabled ? ' sankey-node--disabled' : ''), transform: `translate(${n.x},${n.y})` });

        // header (title bar, colored by node type)
        const header = el('rect', { width: NODE_W, height: HEADER_H, fill: n.color || '#999', class: 'sankey-node-header' });
        header.addEventListener('mousedown', (e) => this._startDrag(key, e));
        group.appendChild(header);

        const label = el('text', { x: 8, y: 17, class: 'sankey-node-label' });
        label.textContent = `${this._nodeTitle(key)}`;
        group.appendChild(label);

        const removeText = el('text', { x: NODE_W - 10, y: 17, class: 'sankey-node-remove' });
        removeText.textContent = '×';
        removeText.addEventListener('mousedown', (e) => { e.stopPropagation(); this._removeNode(key); });
        group.appendChild(removeText);

        // body (properties, Blender-style label/input rows)
        const body = el('rect', { y: HEADER_H, width: NODE_W, height: h - HEADER_H, class: 'sankey-node-body' });
        body.addEventListener('mousedown', (e) => this._startDrag(key, e));
        group.appendChild(body);

        // blank connector row: no label, no input, just where the sockets
        // sit, so a wire never looks like it targets a specific property.
        const connectorRow = el('rect', { x: 0, y: HEADER_H, width: NODE_W, height: ROW_H, class: 'sankey-node-row sankey-node-row--connector' });
        group.appendChild(connectorRow);

        this._drawPropRow(group, 0, 'Priority', () => {
            const input = document.createElement('input');
            input.type = 'number';
            input.className = 'sankey-priority-input';
            input.value = n.priority;
            input.title = 'Priority (higher = evaluated first)';
            input.addEventListener('mousedown', (e) => e.stopPropagation());
            input.addEventListener('change', () => { n.priority = parseInt(input.value, 10) || 0; });
            return input;
        });

        this._drawPropRow(group, 1, 'Disabled', () => {
            const cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.title = 'Disable (exclude from generation)';
            cb.checked = !!n.disabled;
            cb.addEventListener('mousedown', (e) => e.stopPropagation());
            cb.addEventListener('change', () => { n.disabled = cb.checked; this.render(); });
            return cb;
        });

        this._drawPropRow(group, 2, 'Color', () => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'sankey-color-swatch-btn';
            btn.style.background = n.color || DEFAULT_COLORS[this._nodeType(key)];
            btn.title = 'Node color override';
            btn.addEventListener('mousedown', (e) => e.stopPropagation());
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                this._openColorPicker(key, e.clientX, e.clientY);
            });
            return btn;
        });

        // sockets: input (front/left) and output (back/right), Blender-style,
        // always on the blank connector row (see _socketPos)
        const socketY = HEADER_H + ROW_H / 2;
        const inSocket = el('circle', { cx: 0, cy: socketY, r: SOCKET_R, class: 'sankey-socket sankey-socket--in' });
        inSocket.addEventListener('mousedown', (e) => { e.stopPropagation(); this._startConnect(key, 'input', e); });
        group.appendChild(inSocket);

        const outSocket = el('circle', { cx: NODE_W, cy: socketY, r: SOCKET_R, class: 'sankey-socket sankey-socket--out' });
        outSocket.addEventListener('mousedown', (e) => { e.stopPropagation(); this._startConnect(key, 'output', e); });
        group.appendChild(outSocket);

        group.addEventListener('mouseup', () => {
            if (this._connecting && this._connecting.key !== key) {
                const { key: fromKey, endpoint } = this._connecting;
                if (endpoint === 'output') this._tryConnect(fromKey, key);
                else this._tryConnect(key, fromKey);
            }
            this._endConnect();
        });

        this.g.appendChild(group);
    }

    // See the CONNECTOR_SIZE comment: no header, title, or property rows --
    // just a small diamond (a rotated square), sockets, and a delete button.
    _drawConnectorNode(key) {
        const n = this.nodes[key];
        const r = CONNECTOR_SIZE / 2;
        const group = el('g', { class: 'sankey-node sankey-node--connector', transform: `translate(${n.x},${n.y})` });

        const diamond = el('polygon', {
            points: `${r},0 ${CONNECTOR_SIZE},${r} ${r},${CONNECTOR_SIZE} 0,${r}`,
            fill: n.color || DEFAULT_COLORS.connector,
            class: 'sankey-node-connector-diamond',
        });
        diamond.addEventListener('mousedown', (e) => this._startDrag(key, e));
        group.appendChild(diamond);

        const removeText = el('text', { x: CONNECTOR_SIZE + 4, y: 8, class: 'sankey-node-connector-remove' });
        removeText.textContent = '×';
        removeText.addEventListener('mousedown', (e) => { e.stopPropagation(); this._removeNode(key); });
        group.appendChild(removeText);

        // A Connector has no property rows (see the class-level comment on
        // _nodeHeight), so its color override is a small swatch dot next to
        // the diamond instead of a labeled row.
        const colorSwatch = el('circle', {
            cx: -10, cy: r, r: 6, class: 'sankey-node-connector-swatch',
            fill: n.color || DEFAULT_COLORS.connector,
        });
        colorSwatch.addEventListener('mousedown', (e) => e.stopPropagation());
        colorSwatch.addEventListener('click', (e) => {
            e.stopPropagation();
            this._openColorPicker(key, e.clientX, e.clientY);
        });
        group.appendChild(colorSwatch);

        const inSocket = el('circle', { cx: 0, cy: r, r: SOCKET_R, class: 'sankey-socket sankey-socket--in' });
        inSocket.addEventListener('mousedown', (e) => { e.stopPropagation(); this._startConnect(key, 'input', e); });
        group.appendChild(inSocket);

        const outSocket = el('circle', { cx: CONNECTOR_SIZE, cy: r, r: SOCKET_R, class: 'sankey-socket sankey-socket--out' });
        outSocket.addEventListener('mousedown', (e) => { e.stopPropagation(); this._startConnect(key, 'output', e); });
        group.appendChild(outSocket);

        group.addEventListener('mouseup', () => {
            if (this._connecting && this._connecting.key !== key) {
                const { key: fromKey, endpoint } = this._connecting;
                if (endpoint === 'output') this._tryConnect(fromKey, key);
                else this._tryConnect(key, fromKey);
            }
            this._endConnect();
        });

        this.g.appendChild(group);
    }

    _tryConnect(source, target) {
        if (this.edges.some((e) => e.source === source && e.target === target)) return;
        const sourceType = this._nodeType(source);
        const targetType = this._nodeType(target);
        if (sourceType === targetType && MUTUALLY_EXCLUSIVE_TYPES.has(sourceType)) {
            this._showError(
                `An expense's ${sourceType} is always exactly one value, so a ${sourceType} can never `
                + `co-occur with a different ${targetType} on the same expense; this connection could `
                + 'never carry any value.',
            );
            return;
        }
        if (this._wouldCreateCycle(source, target)) {
            this._showError('That connection would create a cycle; Sankey Studio graphs must flow one direction.');
            return;
        }
        if (MUTUALLY_EXCLUSIVE_TYPES.has(targetType)) {
            const locked = this._lockedIdentities()[source];
            const srcLock = locked ? locked[targetType] : null;
            if (srcLock && !srcLock.has(parseNodeKey(target)[1])) {
                this._showError(
                    `Money reaching ${source} is already committed to a different ${targetType} earlier `
                    + 'in this diagram (directly, or through a chain of intermediate nodes), '
                    + `so it can never also match ${target}; this connection could never carry any value.`,
                );
                return;
            }
        }
        this._showError('');
        this.edges.push({ source, target });
        this.render();
    }

    // Mirrors budget/sankey_service.py::locked_identities: for every node,
    // which specific Category/Project identity (if any) its inflow is
    // already provably restricted to by walking the graph backward. See
    // that function's docstring for the full rationale (a catch-all node
    // is transparent to this rule, exactly like any other pass-through
    // node with no identity of its own).
    _lockedIdentities() {
        const parents = {};
        this.edges.forEach((e) => { (parents[e.target] = parents[e.target] || []).push(e.source); });
        const memo = {};
        const resolve = (node, axis) => {
            const cacheKey = `${node} ${axis}`;
            if (cacheKey in memo) return memo[cacheKey];
            memo[cacheKey] = null; // cycle guard
            const [nodeType, ident] = parseNodeKey(node);
            let result;
            if (nodeType === axis) {
                result = new Set([ident]);
            } else {
                const ps = parents[node] || [];
                if (!ps.length) {
                    result = null;
                } else {
                    const vals = ps.map((p) => resolve(p, axis));
                    result = vals.some((v) => v === null)
                        ? null
                        : new Set(vals.flatMap((v) => [...v]));
                }
            }
            memo[cacheKey] = result;
            return result;
        };
        const nodeKeys = Object.keys(this.nodes);
        const result = {};
        [...MUTUALLY_EXCLUSIVE_TYPES].forEach((axis) => {
            nodeKeys.forEach((n) => {
                result[n] = result[n] || {};
                result[n][axis] = resolve(n, axis);
            });
        });
        return result;
    }

    // ── Click-drag-drop connecting (Blender-style, with a live noodle) ──
    _startConnect(key, endpoint, evt) {
        this._connecting = { key, endpoint };
        this._tempLine = el('path', { class: 'sankey-edge sankey-edge--dragging' });
        this.g.appendChild(this._tempLine);
        this._updateTempLine(this._svgPoint(evt));
        this._startAutoPanLoop();
    }

    _updateTempLine(pt) {
        if (!this._tempLine || !this._connecting) return;
        const start = this._socketPos(this._connecting.key, this._connecting.endpoint);
        const worldX = (pt.x - this.pan.x) / this.zoom;
        const worldY = (pt.y - this.pan.y) / this.zoom;
        const d = this._connecting.endpoint === 'output'
            ? this._edgePathD(start.x, start.y, worldX, worldY)
            : this._edgePathD(worldX, worldY, start.x, start.y);
        this._tempLine.setAttribute('d', d);
    }

    _endConnect() {
        if (this._tempLine) { this._tempLine.remove(); this._tempLine = null; }
        this._connecting = null;
        this._stopAutoPanLoop();
    }

    // Nodes far enough apart that they can't both fit on screen at once
    // would otherwise be impossible to wire together without letting go of
    // the drag to pan manually first. While a connection is being dragged,
    // the cursor nearing the viewport edge auto-pans the canvas toward it,
    // continuously (via requestAnimationFrame, not just on mousemove) so it
    // keeps scrolling even if the cursor sits still right at the edge.
    _startAutoPanLoop() {
        if (this._autoPanRAF) return;
        const tick = () => {
            this._autoPanTick();
            this._autoPanRAF = this._connecting ? requestAnimationFrame(tick) : null;
        };
        this._autoPanRAF = requestAnimationFrame(tick);
    }

    _stopAutoPanLoop() {
        if (this._autoPanRAF) {
            cancelAnimationFrame(this._autoPanRAF);
            this._autoPanRAF = null;
        }
    }

    _autoPanTick() {
        if (!this._connecting || !this._lastMouseScreenPos) return;
        const pos = this._lastMouseScreenPos;
        const w = this.svg.clientWidth || 0;
        const h = this.svg.clientHeight || 0;
        let dx = 0;
        let dy = 0;
        if (pos.x < AUTO_PAN_EDGE) dx = AUTO_PAN_SPEED * (1 - pos.x / AUTO_PAN_EDGE);
        else if (pos.x > w - AUTO_PAN_EDGE) dx = -AUTO_PAN_SPEED * (1 - (w - pos.x) / AUTO_PAN_EDGE);
        if (pos.y < AUTO_PAN_EDGE) dy = AUTO_PAN_SPEED * (1 - pos.y / AUTO_PAN_EDGE);
        else if (pos.y > h - AUTO_PAN_EDGE) dy = -AUTO_PAN_SPEED * (1 - (h - pos.y) / AUTO_PAN_EDGE);
        if (dx === 0 && dy === 0) return;
        this.pan.x += dx;
        this.pan.y += dy;
        // Transform-only update, never the full render() -- see
        // _applyTransform's comment; the temp line is then re-anchored to
        // the (unmoved) cursor position under the new pan.
        this._applyTransform();
        this._updateTempLine(pos);
    }

    // ── Drag / zoom / panning ────────────────────────────────────────────
    _startDrag(key, evt) {
        evt.stopPropagation();
        const pt = this._svgPoint(evt);
        this._drag = { key, offsetX: pt.x / this.zoom - this.pan.x / this.zoom - this.nodes[key].x, offsetY: pt.y / this.zoom - this.pan.y / this.zoom - this.nodes[key].y };
    }

    _onMouseMove(evt) {
        const pt = this._svgPoint(evt);
        this._lastMouseScreenPos = pt;
        if (this._drag) {
            const n = this.nodes[this._drag.key];
            const rawX = pt.x / this.zoom - this.pan.x / this.zoom - this._drag.offsetX;
            const rawY = pt.y / this.zoom - this.pan.y / this.zoom - this._drag.offsetY;
            const snapped = this._applySnap(rawX, rawY);
            n.x = snapped.x;
            n.y = snapped.y;
            this.render();
            return;
        }
        if (this._anchorDrag) {
            const { edge, idx, offsetX, offsetY } = this._anchorDrag;
            const rawX = pt.x / this.zoom - this.pan.x / this.zoom - offsetX;
            const rawY = pt.y / this.zoom - this.pan.y / this.zoom - offsetY;
            const snapped = this._applySnap(rawX, rawY);
            edge.anchors[idx].x = snapped.x;
            edge.anchors[idx].y = snapped.y;
            this.render();
            return;
        }
        if (this._connecting) {
            this._updateTempLine(pt);
            return;
        }
        if (this._panDrag) {
            this.pan.x = this._panDrag.startPanX + (pt.x - this._panDrag.startX);
            this.pan.y = this._panDrag.startPanY + (pt.y - this._panDrag.startY);
            this.render();
        }
    }

    _endDrag() {
        this._drag = null;
        this._anchorDrag = null;
    }

    // Click-drag-drop panning the canvas; no x/y limits are enforced.
    _startPan(evt) {
        // Only when the mousedown lands on empty canvas: every interactive
        // element (node header/body, sockets, inputs) already calls
        // stopPropagation() on its own mousedown, so this only ever fires
        // for a genuine background click.
        const pt = this._svgPoint(evt);
        this._panDrag = { startX: pt.x, startY: pt.y, startPanX: this.pan.x, startPanY: this.pan.y };
        this.svg.classList.add('sankey-panning');
    }

    _endPan() {
        this._panDrag = null;
        this.svg.classList.remove('sankey-panning');
    }

    _svgPoint(evt) {
        const rect = this.svg.getBoundingClientRect();
        return { x: evt.clientX - rect.left, y: evt.clientY - rect.top };
    }

    // Zoom so that the world point currently under (screenX, screenY) stays
    // at that same screen position after the zoom changes. Used by both the
    // wheel handler (cursor position) and the +/- buttons (canvas center).
    _zoomAt(newZoom, screenX, screenY) {
        newZoom = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, newZoom));
        if (newZoom === this.zoom) return;
        const worldX = (screenX - this.pan.x) / this.zoom;
        const worldY = (screenY - this.pan.y) / this.zoom;
        this.pan.x = screenX - newZoom * worldX;
        this.pan.y = screenY - newZoom * worldY;
        this.zoom = newZoom;
        this.render();
    }

    _onCanvasWheel(evt) {
        evt.preventDefault();
        const pt = this._svgPoint(evt);
        // Multiplicative and proportional to the actual deltaY: total zoom
        // change tracks total scroll distance, not event count, so a
        // trackpad's stream of tiny events doesn't compound into a huge jump.
        const factor = Math.exp(-evt.deltaY * ZOOM_WHEEL_SENSITIVITY);
        this._zoomAt(this.zoom * factor, pt.x, pt.y);
    }

    _zoomBy(factor) {
        const rect = this.svg.getBoundingClientRect();
        this._zoomAt(this.zoom * factor, rect.width / 2, rect.height / 2);
    }

    // ── Save / Generate ─────────────────────────────────────────────────
    // showFlash is false for generate()'s implicit pre-generate save, so a
    // successful Generate isn't cluttered with a redundant "Graph saved"
    // note on top of the chart itself appearing.
    async save(showFlash = true) {
        this._showError('');
        const resp = await fetch(this.urls.save, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
            body: JSON.stringify({ nodes: this.nodes, edges: this.edges }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            this._showError(data.error || 'Could not save the graph.');
            return;
        }
        if (showFlash) window.showToast('Graph saved.');
    }

    async generate() {
        await this.save(false);
        if (this.error) return;
        const range = window._dateRange.get();
        // Alpine is imported directly into this module (see top of file),
        // so the registered store is reachable via that local binding --
        // window.Alpine is never set by the ES-module build Alpine ships
        // (only its standalone CDN script sets that global).
        const sharing = Alpine.store('sharing').mode;
        this._showError('');
        const resp = await fetch(this.urls.generate, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
            body: JSON.stringify({ date_from: range.from, date_to: range.to, sharing: sharing === 'shared' ? 'shared' : '' }),
        });
        const data = await resp.json();
        if (!resp.ok) {
            this._showError(data.error || 'Could not generate the chart.');
            return;
        }
        this.chart = data;
        this._renderChart();
    }

    // ── Generated chart rendering ────────────────────────────────────────
    _renderChart() {
        this.chartWrap.style.display = 'block';
        this.chartSvg.innerHTML = '';
        this.chartSvg.setAttribute('height', 500);
        if (!this.chart.nodes.length) {
            const t = el('text', { x: 20, y: 30, class: 'sankey-chart-label' });
            t.textContent = 'Nothing to show for this period/mode.';
            this.chartSvg.appendChild(t);
            return;
        }
        try {
            this._drawChart();
        } catch (e) {
            this.chartSvg.innerHTML = '';
            this.chartSvg.setAttribute('height', 60);
            const t = el('text', { x: 20, y: 30, class: 'sankey-chart-label' });
            t.textContent = 'Could not draw the chart. Please try again.';
            this.chartSvg.appendChild(t);
        }
    }

    // How many nodes d3-sankey itself ends up stacking in the same column,
    // for the crowded column that actually determines the tightest fit. Not
    // guessable from the link graph alone (d3-sankey's default "justify"
    // alignment pushes every *sink* node -- one with no outgoing links,
    // regardless of how many hops it is from a root -- to the same
    // rightmost column, so a naive longest-path-from-root estimate
    // routinely undercounts real crowding: a leaf one hop from a root and a
    // leaf five hops deep can end up sharing a column) -- so this runs
    // d3-sankey's own layout once, at a throwaway height, purely to read
    // back each node's real rendered column and count them. Crucially this
    // reads `node.layer` (the post-alignment column d3-sankey actually
    // renders into), not `node.depth` (the pre-alignment longest-path
    // depth) -- those two disagree for exactly the sink nodes `justify`
    // relocates, which is the entire case this needs to get right.
    _probeColumnCounts(linkedNodes, linksForLayout, width) {
        const probe = d3sankey().nodeWidth(18).nodePadding(14).extent([[1, 1], [width - 1, 4000]])({
            nodes: linkedNodes.map((n) => ({ ...n, fixedValue: n.value })),
            links: linksForLayout.map((l) => ({ ...l })),
        });
        const counts = {};
        probe.nodes.forEach((n) => { counts[n.layer] = (counts[n.layer] || 0) + 1; });
        return Math.max(1, ...Object.values(counts));
    }

    // d3-sankey computes each node's value purely from its own links,
    // silently zeroing (and visually collapsing) any node with no links at
    // all -- so a node that's a legitimate root/leaf with real money but no
    // wiring would just vanish from a plain d3-sankey render. Those nodes
    // are drawn separately below the flow diagram as simple value bars,
    // using the real value the backend computed, instead of being handed
    // to d3-sankey's layout at all.
    _drawChart() {
        const width = this.chartSvg.clientWidth || 900;
        const linkedKeys = new Set();
        this.chart.links.forEach((l) => { linkedKeys.add(l.source); linkedKeys.add(l.target); });
        const linkedNodes = this.chart.nodes.filter((n) => linkedKeys.has(n.key));
        const isolatedNodes = this.chart.nodes.filter((n) => !linkedKeys.has(n.key));

        const isolatedRowH = 22;
        const isolatedH = isolatedNodes.length ? isolatedNodes.length * isolatedRowH + 20 : 0;

        let sankeyH = 0;
        let keyIndex = {};
        let linksForLayout = [];
        if (linkedNodes.length) {
            keyIndex = {};
            linkedNodes.forEach((n, i) => { keyIndex[n.key] = i; });
            linksForLayout = this.chart.links.map((l) => ({ source: keyIndex[l.source], target: keyIndex[l.target], value: l.value }));
            // A fixed 480px budget cramped/cut off any column with more
            // than a handful of nodes (nodePadding alone needs
            // (count-1)*14px, on top of each node's own minimum height);
            // size it to the most crowded column d3-sankey itself actually
            // produces instead of a flat constant.
            const maxColumnCount = this._probeColumnCounts(linkedNodes, linksForLayout, width);
            sankeyH = Math.max(320, maxColumnCount * 46, 480 - isolatedH);
        }
        this.chartSvg.setAttribute('height', Math.max(sankeyH + isolatedH, 60));

        const g = el('g');
        this.chartSvg.appendChild(g);

        if (linkedNodes.length) {
            const layout = d3sankey().nodeWidth(18).nodePadding(14).extent([[1, 1], [width - 1, sankeyH - 1]]);
            const graph = layout({
                // fixedValue pins each node's rendered size to the real
                // backend-computed value instead of d3-sankey's own default
                // (max of its own link sums) -- normally the same number,
                // but a "Leaf" node (see sankey_service.py's leaf_keys) can
                // keep part of its own inflow instead of routing all of it
                // onward, so its outgoing links alone would undersize it.
                nodes: linkedNodes.map((n) => ({ ...n, fixedValue: n.value })),
                // Fresh copies: d3-sankey mutates the link/node objects it's
                // handed, and this same linksForLayout data already went
                // through one throwaway probe layout above.
                links: linksForLayout.map((l) => ({ ...l })),
            });

            const linkG = el('g', { fill: 'none' });
            graph.links.forEach((l) => {
                // Colored by the node the flow is heading *into*, not out
                // of -- makes it obvious at a glance which downstream
                // bucket a flow ends up in, instead of everything just
                // inheriting whatever color happened to sit upstream.
                const targetColor = l.target.color || DEFAULT_COLORS[this._nodeType(l.target.key)] || '#999';
                const path = el('path', {
                    d: sankeyLinkHorizontal()(l),
                    stroke: targetColor, 'stroke-opacity': 0.4, 'stroke-width': Math.max(1, l.width),
                });
                const tooltipText = `${l.source.title} -> ${l.target.title}: ${l.value.toFixed(2)}`;
                path.addEventListener('mouseenter', (e) => this._showTooltip(tooltipText, e));
                path.addEventListener('mousemove', (e) => this._moveTooltip(e));
                path.addEventListener('mouseleave', () => this._hideTooltip());
                linkG.appendChild(path);
            });
            g.appendChild(linkG);

            graph.nodes.forEach((n) => {
                const rect = el('rect', {
                    x: n.x0, y: n.y0, width: n.x1 - n.x0, height: n.y1 - n.y0,
                    fill: n.color || DEFAULT_COLORS[this._nodeType(n.key)] || '#4e79a7',
                });
                const tooltipText = `${n.title}: ${n.value.toFixed(2)}`;
                rect.addEventListener('mouseenter', (e) => this._showTooltip(tooltipText, e));
                rect.addEventListener('mousemove', (e) => this._moveTooltip(e));
                rect.addEventListener('mouseleave', () => this._hideTooltip());
                g.appendChild(rect);

                // A Connector is pure wiring with no meaning of its own,
                // so the chart only shows it as an unlabeled bar; the name
                // is still available on hover via the tooltip above.
                if (this._nodeType(n.key) === 'connector') return;

                const label = el('text', { x: n.x0 < width / 2 ? n.x1 + 6 : n.x0 - 6, y: (n.y0 + n.y1) / 2, 'text-anchor': n.x0 < width / 2 ? 'start' : 'end', class: 'sankey-chart-label' });
                label.textContent = n.title;
                g.appendChild(label);
            });
        }

        if (isolatedNodes.length) {
            const maxVal = Math.max(...isolatedNodes.map((n) => n.value), 1);
            const barMaxW = Math.max(width - 140, 40);
            isolatedNodes.forEach((n, i) => {
                const y = sankeyH + 10 + i * isolatedRowH;
                const barW = Math.max(2, (n.value / maxVal) * barMaxW);
                const rect = el('rect', {
                    x: 120, y, width: barW, height: isolatedRowH - 6,
                    fill: n.color || DEFAULT_COLORS[this._nodeType(n.key)] || '#4e79a7',
                });
                const tooltipText = `${n.title}: ${n.value.toFixed(2)} (not connected to anything)`;
                rect.addEventListener('mouseenter', (e) => this._showTooltip(tooltipText, e));
                rect.addEventListener('mousemove', (e) => this._moveTooltip(e));
                rect.addEventListener('mouseleave', () => this._hideTooltip());
                g.appendChild(rect);

                if (this._nodeType(n.key) === 'connector') return;

                const label = el('text', { x: 0, y: y + (isolatedRowH - 6) / 2 + 4, class: 'sankey-chart-label' });
                label.textContent = n.title;
                g.appendChild(label);
            });
        }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const cfg = window.SANKEY_CONFIG;
    if (!cfg) return;
    window._sankeyEditor = new SankeyEditor(cfg);
});
