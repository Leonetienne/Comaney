import Alpine from 'alpinejs';
import Chart from 'chart.js/auto';
import { EditorView, basicSetup } from 'codemirror';
import { Compartment, EditorState } from '@codemirror/state';
import { yaml } from '@codemirror/lang-yaml';
import { oneDark } from '@codemirror/theme-one-dark';

const PALETTE = [
    '#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f',
    '#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac',
    '#86bcb6','#f1ce63','#d4a6c8','#a0cbe8','#ffbe7d',
];

const GRID_GAP = 12;
const ROW_H    = 90; // px — fixed row height, independent of viewport width

function dashboardBoard() {
    return {
        // ── State ─────────────────────────────────────────────────────────────
        cards:    [],
        charts:   {},       // { cardId: Chart }
        loading:  true,
        currency: '',
        csrf:     '',

        // API URLs (filled from window.DASHBOARD_CONFIG)
        urlCards:    '',
        urlReorder:  '',
        urlPresets:  '',

        // Period
        periodYear:  '',
        periodMonth: '',
        periodMode:  '',

        // Edit modal
        editCard:   null,   // full card object being edited
        editYaml:   '',
        editError:  '',
        editSaving: false,

        // New card dialog
        addOpen:      false,
        addYaml:      '',
        addYamlDirty: false,
        addError:     '',
        addSaving:    false,
        presets:      [],

        // CodeMirror editor instances
        _addEditor:         null,
        _editEditor:        null,
        _programmaticEdit:  false,

        // Drag-drop
        dragId:        null,
        dragOverId:    null,

        // Resize
        _resizeState:  null,
        _resizeObserver: null,

        // ── Init ──────────────────────────────────────────────────────────────
        async init() {
            const cfg      = window.DASHBOARD_CONFIG;
            this.currency  = cfg.currency;
            this.urlCards  = cfg.urlCards;
            this.urlReorder = cfg.urlReorder;
            this.urlPresets = cfg.urlPresets;
            this.periodYear  = cfg.year;
            this.periodMonth = cfg.month;
            this.periodMode  = cfg.mode;
            this.csrf = document.querySelector('meta[name="csrf-token"]').content;

            await this.fetchCards();
            this._setupResize();
        },

        // ── Grid row-height sync ──────────────────────────────────────────────
        _setupResize() {
            // Observe the outer container (always visible) for width changes;
            // write the computed columns/row-height onto the inner .dash-grid.
            const container = this.$el;
            const sync = () => {
                const dashGrid = container.querySelector('.dash-grid');
                if (dashGrid) this._syncRowHeight(container.offsetWidth, dashGrid);
            };
            this._resizeObserver = new ResizeObserver(sync);
            this._resizeObserver.observe(container);
            sync();
        },

        _syncRowHeight(available, dashGrid) {
            const cols = available < 560 ? 6 : 12;
            this._currentCols = cols;
            const colW = (available - GRID_GAP * (cols - 1)) / cols;
            this._colW = colW + GRID_GAP;
            this._rowH = ROW_H + GRID_GAP;
            dashGrid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
            dashGrid.style.setProperty('--dash-row-h', ROW_H + 'px');
        },

        // ── Period query params ────────────────────────────────────────────────
        get _periodParams() {
            const p = new URLSearchParams({ year: this.periodYear });
            if (this.periodMode === 'year') p.set('view', 'year');
            else p.set('month', this.periodMonth);
            return p.toString();
        },

        // ── Fetch / refresh ───────────────────────────────────────────────────
        async fetchCards() {
            this.loading = true;
            this._destroyCharts();
            try {
                const resp = await fetch(this.urlCards + '?' + this._periodParams);
                const data = await resp.json();
                this.cards = data.cards || [];
            } finally {
                this.loading = false;
            }
            await Alpine.nextTick();
            await new Promise(r => requestAnimationFrame(r));
            await Alpine.nextTick();
            this._renderCharts();
        },

        // ── Chart.js rendering ────────────────────────────────────────────────
        _destroyCharts() {
            Object.values(this.charts).forEach(c => c.destroy());
            this.charts = {};
        },

        _renderCharts() {
            const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            Chart.defaults.color       = dark ? '#888' : '#666';
            Chart.defaults.borderColor = dark ? '#333' : '#e8e8e8';

            this.cards.forEach(card => this._renderChart(card, dark));
        },

        _renderChart(card, dark) {
            const type = card.config && card.config.type;
            if (type !== 'bar-chart' && type !== 'pie-chart') return;
            if (!card.data || !card.data.labels || !card.data.labels.length) return;

            const canvas = document.getElementById('chart-' + card.id);
            if (!canvas) return;

            if (this.charts[card.id]) this.charts[card.id].destroy();

            const n      = card.data.labels.length;
            const colors = Array.from({ length: n }, (_, i) => PALETTE[i % PALETTE.length]);
            const cur    = this.currency;

            const linkTpl  = card.config.link_template || '';
            const onClickFn = linkTpl ? (_evt, elements) => {
                if (!elements.length) return;
                const label = this.charts[card.id].data.labels[elements[0].index];
                const slug = label === 'Uncategorized' ? 'none' : encodeURIComponent(label);
                window.location.href = linkTpl.replace('$GROUP_NAME', slug);
            } : undefined;
            const onHoverFn = linkTpl ? (_evt, elements) => {
                canvas.style.cursor = elements.length ? 'pointer' : 'default';
            } : undefined;

            if (type === 'pie-chart') {
                // Size canvas to fill the card body so Chart.js doesn't over-expand it
                const body = canvas.closest('.dash-card-body');
                const avail = body ? Math.max(80, body.offsetHeight - 24) : 180;
                canvas.style.width  = '100%';
                canvas.style.height = avail + 'px';
                this.charts[card.id] = new Chart(canvas, {
                    type: 'pie',
                    data: {
                        labels: card.data.labels,
                        datasets: [{
                            data: card.data.values,
                            backgroundColor: colors,
                            borderWidth: 2,
                            borderColor: dark ? '#1c1c1c' : '#fff',
                        }],
                    },
                    options: {
                        animation: false,
                        responsive: true,
                        maintainAspectRatio: false,
                        onClick: onClickFn,
                        onHover: onHoverFn,
                        plugins: {
                            legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } },
                            tooltip: { callbacks: { label: c => ` ${c.label}: ${c.parsed.toFixed(2)} ${cur}` } },
                        },
                    },
                });
            } else {
                // bar-chart (horizontal)
                canvas.height = Math.max(60, n * 18);
                this.charts[card.id] = new Chart(canvas, {
                    type: 'bar',
                    data: {
                        labels: card.data.labels,
                        datasets: [{
                            data: card.data.values,
                            backgroundColor: colors,
                            borderRadius: 3,
                            borderSkipped: false,
                            categoryPercentage: 0.85,
                            barPercentage: 0.9,
                        }],
                    },
                    options: {
                        animation: false,
                        indexAxis: 'y',
                        onClick: onClickFn,
                        onHover: onHoverFn,
                        plugins: {
                            legend: { display: false },
                            tooltip: { callbacks: { label: c => ` ${c.parsed.x.toFixed(2)} ${cur}` } },
                        },
                        scales: {
                            y: { grid: { display: false }, ticks: { font: { size: 11 }, autoSkip: false } },
                        },
                    },
                });
            }
        },

        // ── Card style (grid placement) ────────────────────────────────────────
        cardStyle(card) {
            return `grid-column: span ${card.width}; grid-row: span ${card.height};`;
        },

        // ── Drag-drop ─────────────────────────────────────────────────────────
        onDragStart(cardId, e) {
            this.dragId = cardId;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', String(cardId));
        },

        onDragOver(cardId, e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            this.dragOverId = cardId;
        },

        onDragLeave() {
            this.dragOverId = null;
        },

        onDragEnd() {
            this.dragId     = null;
            this.dragOverId = null;
        },

        async onDrop(targetId, e) {
            e.preventDefault();
            const fromId = this.dragId;
            this.dragId     = null;
            this.dragOverId = null;

            if (fromId == null || fromId === targetId) return;

            const fromIdx = this.cards.findIndex(c => c.id === fromId);
            const toIdx   = this.cards.findIndex(c => c.id === targetId);
            if (fromIdx < 0 || toIdx < 0) return;

            // Reorder local state
            const moved = this.cards.splice(fromIdx, 1)[0];
            this.cards.splice(toIdx, 0, moved);

            // Assign new 1-based positions
            const positions = this.cards.map((c, i) => ({ id: c.id, position: i + 1 }));
            this.cards.forEach((c, i) => { c.position = i + 1; });

            await this._postJson(this.urlReorder, { positions });
        },

        // ── Resize (pointer events on the handle) ─────────────────────────────
        onResizeStart(cardId, e) {
            e.stopPropagation();
            e.preventDefault();
            const colW = this._colW || 130;
            const rowH = this._rowH || 130;
            const card = this.cards.find(c => c.id === cardId);
            if (!card) return;

            this._resizeState = {
                cardId,
                startX: e.clientX,
                startY: e.clientY,
                startW: card.width,
                startH: card.height,
                colW,
                rowH,
            };
            e.target.setPointerCapture(e.pointerId);
        },

        onResizeMove(cardId, e) {
            const s = this._resizeState;
            if (!s || s.cardId !== cardId) return;

            const dx   = e.clientX - s.startX;
            const dy   = e.clientY - s.startY;
            const newW = Math.max(1, Math.min(this._currentCols || MAX_COLS, s.startW + Math.round(dx / s.colW)));
            const newH = Math.max(1, s.startH + Math.round(dy / s.rowH));

            const card = this.cards.find(c => c.id === cardId);
            if (card) {
                card.width  = newW;
                card.height = newH;
            }
        },

        async onResizeEnd(cardId, e) {
            const s = this._resizeState;
            if (!s || s.cardId !== cardId) return;
            this._resizeState = null;

            const card = this.cards.find(c => c.id === cardId);
            if (!card) return;

            const resp = await this._patchJson(
                this.urlCards.replace(/\/$/, '') + '/' + cardId + '/resize/',
                { width: card.width, height: card.height },
            );
            const data = await resp.json();
            if (data.yaml_config) card.yaml_config = data.yaml_config;

            // Re-render chart for this card after size change
            await Alpine.nextTick();
            await new Promise(r => requestAnimationFrame(r));
            const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            if (this.charts[cardId]) this.charts[cardId].destroy();
            delete this.charts[cardId];
            this._renderChart(card, dark);
        },

        // ── Edit modal ────────────────────────────────────────────────────────
        async openEdit(card) {
            this.editCard  = card;
            this.editYaml  = card.yaml_config;
            this.editError = '';
            await Alpine.nextTick();
            const el = this.$refs.editEditorEl;
            if (!this._editEditor) {
                this._editEditor = this._makeEditor(el, card.yaml_config, v => { this.editYaml = v; });
            } else {
                this._setEditorContent(this._editEditor, card.yaml_config);
                this._editEditor.focus();
            }
        },

        closeEdit() {
            this.editCard = null;
        },

        async saveEdit() {
            if (!this.editCard || this.editSaving) return;
            this.editSaving = true;
            this.editError  = '';
            try {
                const resp = await this._patchJson(
                    this.urlCards.replace(/\/$/, '') + '/' + this.editCard.id + '/',
                    { yaml_config: this.editYaml },
                );
                const data = await resp.json();
                if (!resp.ok) {
                    this.editError = data.error || 'Save failed';
                    return;
                }
                this.editCard = null;
                await this.fetchCards();
            } finally {
                this.editSaving = false;
            }
        },

        async deleteCard(cardId) {
            try { await window.confirmDialog('Delete this card?', 'Delete'); } catch (_) { return; }
            await this._deleteReq(this.urlCards.replace(/\/$/, '') + '/' + cardId + '/');
            this.editCard = null;
            await this.fetchCards();
        },

        // ── New card dialog ───────────────────────────────────────────────────
        async openAdd() {
            this.addOpen      = true;
            this.addYaml      = '';
            this.addYamlDirty = false;
            this.addError     = '';
            await Alpine.nextTick();
            const el = this.$refs.addEditorEl;
            if (!this._addEditor) {
                this._addEditor = this._makeEditor(el, '', v => {
                    this.addYaml      = v;
                    this.addYamlDirty = v.trim() !== '';
                });
            } else {
                this._setEditorContent(this._addEditor, '');
                this._addEditor.focus();
            }
            if (!this.presets.length) {
                try {
                    const resp = await fetch(this.urlPresets);
                    const data = await resp.json();
                    this.presets = data.presets || [];
                } catch (_) {}
            }
        },

        closeAdd() {
            this.addOpen = false;
        },

        async loadPreset(yaml) {
            if (this.addYamlDirty) {
                try { await window.confirmDialog('Overwrite your changes with this preset?', 'Overwrite'); }
                catch (_) { return; }
            }
            this.addYaml      = yaml;
            this.addYamlDirty = false;
            if (this._addEditor) this._setEditorContent(this._addEditor, yaml);
        },

        async saveAdd() {
            if (this.addSaving) return;
            this.addSaving = true;
            this.addError  = '';
            try {
                const resp = await this._postJson(this.urlCards, { yaml_config: this.addYaml });
                const data = await resp.json();
                if (!resp.ok) {
                    this.addError = data.error || 'Create failed';
                    return;
                }
                this.addOpen = false;
                await this.fetchCards();
            } finally {
                this.addSaving = false;
            }
        },

        // ── CodeMirror helpers ────────────────────────────────────────────────
        _makeEditor(el, initialDoc, onChange) {
            const darkMQ   = window.matchMedia('(prefers-color-scheme: dark)');
            const themeC   = new Compartment();
            const view = new EditorView({
                state: EditorState.create({
                    doc: initialDoc,
                    extensions: [
                        basicSetup,
                        yaml(),
                        themeC.of(darkMQ.matches ? oneDark : []),
                        EditorView.updateListener.of(u => {
                            if (u.docChanged && !this._programmaticEdit) onChange(u.state.doc.toString());
                        }),
                    ],
                }),
                parent: el,
            });
            darkMQ.addEventListener('change', e => {
                view.dispatch({ effects: themeC.reconfigure(e.matches ? oneDark : []) });
            });
            return view;
        },

        _setEditorContent(editor, content) {
            this._programmaticEdit = true;
            editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: content } });
            this._programmaticEdit = false;
        },

        // ── Helpers ───────────────────────────────────────────────────────────
        async _postJson(url, body) {
            return fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
                body: JSON.stringify(body),
            });
        },

        async _patchJson(url, body) {
            return fetch(url, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
                body: JSON.stringify(body),
            });
        },

        async _deleteReq(url) {
            return fetch(url, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': this.csrf },
            });
        },

        // Format a value for display in a cell card
        formatValue(val) {
            if (val === null || val === undefined) return '–';
            const n = parseFloat(val);
            if (isNaN(n)) return String(val);
            return Math.round(n).toString();
        },

        // Render cell text, substituting $VALUE and $CURRENCY_SYMBOL in template
        cellText(card) {
            const val = this.formatValue(card.data && card.data.value);
            const tpl = (card.config && card.config.template) || '$VALUE $CURRENCY_SYMBOL';
            return tpl.replace('$VALUE', val).replace('$CURRENCY_SYMBOL', this.currency);
        },

        // Hex → [h°, s%, l%]
        _hexToHsl(hex) {
            const n = parseInt(hex.replace('#', ''), 16);
            let r = ((n >> 16) & 255) / 255;
            let g = ((n >>  8) & 255) / 255;
            let b = ( n        & 255) / 255;
            const max = Math.max(r, g, b), min = Math.min(r, g, b);
            let h = 0, s = 0;
            const l = (max + min) / 2;
            if (max !== min) {
                const d = max - min;
                s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
                switch (max) {
                    case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
                    case g: h = ((b - r) / d + 2) / 6; break;
                    case b: h = ((r - g) / d + 4) / 6; break;
                }
            }
            return [h * 360, s * 100, l * 100];
        },

        // Return inline style string for a coloured cell card.
        // Text is the same hue/saturation as the background but shifted:
        //   dark mode  → much lighter  (+55 L, clamped to 95)
        //   light mode → much darker   (−40 L, clamped to  5)
        cardColorStyle(cfg) {
            const dark  = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const color = dark
                ? (cfg.color_darkmode  || cfg.color)
                : (cfg.color_lightmode || cfg.color);
            if (!color) return '';
            try {
                const [h, s, l] = this._hexToHsl(color);
                const textL = dark
                    ? Math.min(95, l + 55)
                    : Math.max( 5, l - 40);
                const fmt = v => v.toFixed(1);
                return `background:${color};color:hsl(${fmt(h)},${fmt(s)}%,${fmt(textL)}%)`;
            } catch (_) {
                return `background:${color}`;
            }
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('dashboardBoard', dashboardBoard);
});

Alpine.start();
