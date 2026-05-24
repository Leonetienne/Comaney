import Alpine from 'alpinejs';
import Chart from 'chart.js/auto';
import dateRange from './date-range.js';

// Expose singleton for the date-range-nav partial inline script
window._dateRange = dateRange;
import { EditorView, basicSetup } from 'codemirror';
import { Compartment, EditorState } from '@codemirror/state';
import { yaml } from '@codemirror/lang-yaml';
import { oneDark } from '@codemirror/theme-one-dark';

const PALETTE = [
    '#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f',
    '#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ac',
    '#86bcb6','#f1ce63','#d4a6c8','#a0cbe8','#ffbe7d',
];

const TYPE_ABBR = {
    expense:     'EX',
    income:      'IN',
    savings_dep: 'SD',
    savings_wit: 'SW',
    carry_over:  'CO',
};

const GRID_GAP = 12;
const ROW_H    = 90; // px — fixed row height, independent of viewport width

// Delay (ms) before a hovered tab becomes a drop target while dragging a card
const TAB_HOVER_DELAY = 400;

function dashboardBoard() {
    return {
        // ── State ─────────────────────────────────────────────────────────────
        cards:    [],
        charts:   {},       // { cardId: Chart }
        loading:  true,
        currency: '',
        csrf:     '',

        // API URLs (filled from window.DASHBOARD_CONFIG)
        urlCards:            '',
        urlReorder:          '',
        urlPresets:          '',
        urlReset:            '',
        urlDashboards:       '',
        urlDashboardReorder: '',

        // Current dashboard identity
        dashboardId:      0,
        isFirstDashboard: false,
        dashboards:       [],   // [{id, title, sorting, url}]

        // Date range
        dateFrom:    '',
        dateTo:      '',
        sharingMode: '',

        // Edit modal
        editCard:   null,
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

        // Card drag-drop (card-to-card reorder)
        dragId:        null,
        dragOverId:    null,

        // Tab bar
        renamingTabId:    null,
        renamingTabTitle: '',
        addTabOpen:       false,
        addTabTitle:      '',

        // Drag card onto tab
        _tabHoverTimer:  null,
        tabDragOverId:   null,   // tab being hovered during card drag

        // Tab drag-reorder
        _tabDragId:      null,

        // Resize
        _resizeState:    null,
        _resizeObserver: null,

        // Mobile
        mobileSelectorOpen:    false,
        mobileSelectorAddOpen: false,

        // Mobile swipe between dashboards
        _swipeStartX: null,
        _swipeStartY: null,

        // Mobile touch-drag card between dashboards
        touchDragging:    false,
        isMobileEdgeActive: false,
        touchEdge:        null,
        _touchDragCardId: null,
        _touchEdgeTimer:  null,

        // ── Init ──────────────────────────────────────────────────────────────
        async init() {
            const cfg              = window.DASHBOARD_CONFIG;
            this.currency          = cfg.currency;
            this.urlCards          = cfg.urlCards;
            this.urlReorder        = cfg.urlReorder;
            this.urlPresets        = cfg.urlPresets;
            this.urlReset          = cfg.urlReset;
            this.urlDashboards     = cfg.urlDashboards;
            this.urlDashboardReorder = cfg.urlDashboardReorder;
            this.dashboardId       = cfg.dashboardId;
            this.isFirstDashboard  = cfg.isFirstDashboard;
            this.dashboards        = cfg.dashboards || [];
            this.sharingMode       = this.$store.sharing.mode;
            this.csrf = document.querySelector('meta[name="csrf-token"]').content;

            const cur = dateRange.get();
            this.dateFrom = cur.from;
            this.dateTo   = cur.to;

            this.$watch('$store.sharing.mode', mode => {
                this.sharingMode = mode;
                this.fetchCards();
            });

            window.addEventListener('daterangechange', (e) => {
                this.dateFrom = e.detail.from;
                this.dateTo   = e.detail.to;
                this.fetchCards();
            });

            await this.fetchCards();
            this._setupResize();
        },

        // ── Grid row-height sync ──────────────────────────────────────────────
        _setupResize() {
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

        // ── Date range query params ────────────────────────────────────────────
        get _periodParams() {
            const p = new URLSearchParams();
            p.set('date_from', this.dateFrom);
            p.set('date_to',   this.dateTo);
            if (this.sharingMode === 'shared') p.set('sharing', 'shared');
            return p.toString();
        },

        // Build the URL for a tab, preserving current date range params
        _tabUrl(tab) {
            const qs = this._periodParams;
            return tab.url + (qs ? '?' + qs : '');
        },

        // ── Navigation helper ─────────────────────────────────────────────────
        _navTo(url) {
            if (!url) return;
            window.location.href = url;
        },

        navigateToTab(tab) {
            window.location.href = this._tabUrl(tab);
        },

        // ── Fetch / refresh ───────────────────────────────────────────────────
        async fetchCards() {
            this.loading = true;
            this._destroyCharts();
            try {
                const resp = await fetch(this.urlCards + '&' + this._periodParams);
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
            if (type === 'line-chart') { this._renderLineChart(card, dark); return; }
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
                this._navTo(linkTpl.replace('$GROUP_NAME', slug));
            } : undefined;
            const onHoverFn = linkTpl ? (_evt, elements) => {
                canvas.style.cursor = elements.length ? 'pointer' : 'default';
            } : undefined;

            if (type === 'pie-chart') {
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

        _renderLineChart(card, dark) {
            if (!card.data || !card.data.labels || !card.data.labels.length) return;
            if (!card.data.series || !card.data.series.length) return;

            const canvas = document.getElementById('chart-' + card.id);
            if (!canvas) return;

            if (this.charts[card.id]) this.charts[card.id].destroy();

            const labels = card.data.labels;
            const cur    = this.currency;

            const fmtDate = iso => {
                const d   = new Date(iso + 'T00:00:00');
                const day = String(d.getDate()).padStart(2, '0');
                const mon = d.toLocaleString('en', { month: 'short' });
                return `${day}. ${mon}`;
            };

            const tension      = (card.config && card.config.render_type) === 'linear' ? 0 : 0.35;
            const cfg          = card.config || {};

            const datasets = card.data.series.map((s, i) => {
                const color = s.color || PALETTE[i % PALETTE.length];
                return {
                    label:           s.label,
                    data:            s.values,
                    borderColor:     color,
                    backgroundColor: color + '28',
                    borderWidth:     2,
                    pointRadius:     labels.length > 60 ? 0 : 2,
                    pointHoverRadius: 4,
                    tension,
                    fill:            false,
                };
            });

            const body  = canvas.closest('.dash-card-body');
            const avail = body ? Math.max(80, body.offsetHeight - 8) : 180;
            canvas.style.width  = '100%';
            canvas.style.height = avail + 'px';

            const bucketStarts = card.data.bucket_starts || labels;
            const seriesCfg    = cfg.series || [];
            const hasAnyLink   = seriesCfg.some(s => s.link_template);

            this.charts[card.id] = new Chart(canvas, {
                type: 'line',
                data: { labels, datasets },
                options: {
                    animation: false,
                    responsive: true,
                    maintainAspectRatio: false,
                    onClick: hasAnyLink ? (event, elements) => {
                        if (!elements.length) return;
                        const si  = elements[0].datasetIndex;
                        const idx = elements[0].index;
                        const lt  = seriesCfg[si] && seriesCfg[si].link_template;
                        if (!lt) return;
                        this._navTo(lt
                            .replace(/\$START_DATE/g, bucketStarts[idx])
                            .replace(/\$END_DATE/g,   labels[idx]));
                    } : undefined,
                    onHover: hasAnyLink ? (event, elements) => {
                        if (!event.native) return;
                        const si = elements.length ? elements[0].datasetIndex : -1;
                        const lt = si >= 0 && seriesCfg[si] && seriesCfg[si].link_template;
                        event.native.target.style.cursor = lt ? 'pointer' : 'default';
                    } : undefined,
                    plugins: {
                        legend: { position: 'bottom', labels: { boxWidth: 12, padding: 12, font: { size: 11 } } },
                        tooltip: { callbacks: {
                            title: items => fmtDate(labels[items[0].dataIndex]),
                            label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)} ${cur}`,
                        }},
                    },
                    scales: {
                        x: {
                            ticks: {
                                maxTicksLimit: 8,
                                maxRotation: 45,
                                minRotation: 20,
                                callback: (_val, idx) => fmtDate(labels[idx]),
                            },
                            grid: { display: false },
                        },
                        y: (() => {
                            const s = { ticks: { font: { size: 11 } } };
                            if (cfg.suggested_min != null) s.suggestedMin = cfg.suggested_min;
                            if (cfg.suggested_max != null) s.suggestedMax = cfg.suggested_max;
                            const allVals = datasets.flatMap(d => d.data);
                            if (cfg.limit_max != null && Math.max(...allVals) > cfg.limit_max) s.max = cfg.limit_max;
                            if (cfg.limit_min != null && Math.min(...allVals) < cfg.limit_min) s.min = cfg.limit_min;
                            return s;
                        })(),
                    },
                },
            });
        },

        // ── Mobile detection ──────────────────────────────────────────────────
        _isMobile() {
            return (this._currentCols || 12) <= 6;
        },

        // ── Card style (grid placement) ────────────────────────────────────────
        cardStyle(card) {
            const mob = this._isMobile();

            if (card.config && card.config.type === 'spacer') {
                const hideOn = card.config.hide_on || '';
                if ((hideOn === 'mobile' && mob) || (hideOn === 'desktop' && !mob)) {
                    return 'display:none;';
                }
            }

            const w   = (mob && card.mobile_width    != null) ? card.mobile_width    : card.width;
            const h   = (mob && card.mobile_height   != null) ? card.mobile_height   : card.height;
            const ord = (mob && card.mobile_position != null) ? card.mobile_position : card.position;
            return `grid-column: span ${w}; grid-row: span ${h}; order: ${ord};`;
        },

        // ── Card drag-drop (reorder within dashboard) ─────────────────────────
        onDragStart(cardId, e) {
            this.dragId = cardId;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', String(cardId));
        },

        onDragOver(cardId, e) {
            // Don't handle if the user is dragging a TAB (not a card)
            if (this._tabDragId !== null) return;
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
            this._clearTabHoverTimer();
            this.tabDragOverId = null;
        },

        async onDrop(targetId, e) {
            e.preventDefault();
            const fromId = this.dragId;
            this.dragId     = null;
            this.dragOverId = null;

            if (fromId == null || fromId === targetId) return;

            const mob = this._isMobile();

            if (mob) {
                const getMob = c => c.mobile_position ?? c.position;
                const mobileOrder = [...this.cards].sort((a, b) => getMob(a) - getMob(b));
                const fromIdx = mobileOrder.findIndex(c => c.id === fromId);
                const toIdx   = mobileOrder.findIndex(c => c.id === targetId);
                if (fromIdx < 0 || toIdx < 0) return;

                const moved = mobileOrder.splice(fromIdx, 1)[0];
                mobileOrder.splice(toIdx, 0, moved);
                mobileOrder.forEach((c, i) => { c.mobile_position = i + 1; });

                const positions = this.cards.map(c => ({ id: c.id, position: c.mobile_position }));
                const resp = await this._postJson(this.urlReorder, { positions, mobile: true });
                const data = await resp.json();
                if (data.cards) {
                    const yamlMap = Object.fromEntries(data.cards.map(c => [c.id, c.yaml_config]));
                    this.cards.forEach(c => { if (yamlMap[c.id]) c.yaml_config = yamlMap[c.id]; });
                }
            } else {
                const fromIdx = this.cards.findIndex(c => c.id === fromId);
                const toIdx   = this.cards.findIndex(c => c.id === targetId);
                if (fromIdx < 0 || toIdx < 0) return;

                const moved = this.cards.splice(fromIdx, 1)[0];
                this.cards.splice(toIdx, 0, moved);

                const positions = this.cards.map((c, i) => ({ id: c.id, position: i + 1 }));
                this.cards.forEach((c, i) => { c.position = i + 1; });

                const resp = await this._postJson(this.urlReorder, { positions, mobile: false });
                const data = await resp.json();
                if (data.cards) {
                    const yamlMap = Object.fromEntries(data.cards.map(c => [c.id, c.yaml_config]));
                    this.cards.forEach(c => { if (yamlMap[c.id]) c.yaml_config = yamlMap[c.id]; });
                }
            }
        },

        // ── Drag card onto a tab ──────────────────────────────────────────────
        onTabDragOver(tabId, e) {
            // Only handle if a card (not a tab) is being dragged
            if (this._tabDragId !== null) return;
            if (this.dragId === null) return;
            if (tabId === this.dashboardId) return; // already here

            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';

            if (this.tabDragOverId !== tabId) {
                this._clearTabHoverTimer();
                this.tabDragOverId = tabId;
                // After TAB_HOVER_DELAY, highlight the tab as a drop target
                this._tabHoverTimer = setTimeout(() => {
                    this.tabDragOverId = tabId;
                }, TAB_HOVER_DELAY);
            }
        },

        onTabDragLeave(e) {
            // Only clear if leaving the tab element entirely
            if (this._tabDragId !== null) return;
            this._clearTabHoverTimer();
            this.tabDragOverId = null;
        },

        async onTabDrop(tabId, e) {
            this._clearTabHoverTimer();
            this.tabDragOverId = null;

            // If a tab is being dragged (reorder), handle that instead
            if (this._tabDragId !== null) {
                await this._finishTabReorder(tabId);
                return;
            }

            // Otherwise, move the card to the target dashboard
            const cardId = this.dragId;
            if (!cardId || tabId === this.dashboardId) return;
            this.dragId = null;

            const url = this.urlCards.split('?')[0].replace(/\/$/, '') + '/' + cardId + '/';
            await this._patchJson(url, { dashboard_id: tabId });

            // Remove card from current view
            this.cards = this.cards.filter(c => c.id !== cardId);
            await Alpine.nextTick();
            this._renderCharts();
        },

        _clearTabHoverTimer() {
            if (this._tabHoverTimer) {
                clearTimeout(this._tabHoverTimer);
                this._tabHoverTimer = null;
            }
        },

        // ── Tab drag-reorder ──────────────────────────────────────────────────
        onTabDragStart(tabId, e) {
            this._tabDragId = tabId;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', 'tab:' + tabId);
        },

        onTabDragEnd() {
            this._tabDragId = null;
            this.tabDragOverId = null;
        },

        async _finishTabReorder(targetTabId) {
            const fromId = this._tabDragId;
            this._tabDragId = null;
            if (!fromId || fromId === targetTabId) return;

            const fromIdx = this.dashboards.findIndex(d => d.id === fromId);
            const toIdx   = this.dashboards.findIndex(d => d.id === targetTabId);
            if (fromIdx < 0 || toIdx < 0) return;

            const moved = this.dashboards.splice(fromIdx, 1)[0];
            this.dashboards.splice(toIdx, 0, moved);

            const order = this.dashboards.map(d => d.id);
            this.dashboards.forEach((d, i) => { d.sorting = i; });

            await this._postJson(this.urlDashboardReorder, { order });
        },

        // ── Tab bar: create dashboard ─────────────────────────────────────────
        openAddTab() {
            this.addTabOpen  = true;
            this.addTabTitle = '';
            // Focus is handled by x-init="$nextTick(() => $el.focus())" on the input
        },

        closeAddTab() {
            this.addTabOpen  = false;
            this.addTabTitle = '';
        },

        async submitAddTab(fromMobile = false) {
            const title = this.addTabTitle.trim() || 'Dashboard';
            const resp = await this._postJson(this.urlDashboards, { title });
            if (!resp.ok) return;
            const data = await resp.json();
            const newDash = data.dashboard;
            if (fromMobile) {
                this.mobileSelectorAddOpen = false;
                this.mobileSelectorOpen    = false;
            } else {
                this.closeAddTab();
            }
            this.addTabTitle = '';
            window.location.href = this._tabUrl(newDash);
        },

        // ── Tab bar: rename dashboard ─────────────────────────────────────────
        async startRenameTab(tab) {
            if (tab.id !== this.dashboardId) return; // only rename active tab via dblclick
            this.renamingTabId    = tab.id;
            this.renamingTabTitle = tab.title;
            await Alpine.nextTick();
            // x-ref keys are static strings inside x-for — use querySelector instead
            const inp = this.$el.querySelector('.dash-tab--active .dash-tab-rename-input');
            if (inp) { inp.focus(); inp.select(); }
        },

        cancelRenameTab() {
            this.renamingTabId    = null;
            this.renamingTabTitle = '';
        },

        async commitRenameTab(tab) {
            const title = this.renamingTabTitle.trim();
            if (!title || title === tab.title) { this.cancelRenameTab(); return; }

            const url  = this.urlDashboards.replace(/\/$/, '') + '/' + tab.id + '/';
            const resp = await this._patchJson(url, { title });
            if (resp.ok) {
                tab.title = title;
                const found = this.dashboards.find(d => d.id === tab.id);
                if (found) found.title = title;
            }
            this.cancelRenameTab();
        },

        // ── Tab bar: delete dashboard ─────────────────────────────────────────
        async deleteTab(tab) {
            if (this.dashboards.length <= 1) return;
            try { await window.confirmDialog('Delete this dashboard and all its cards?', 'Delete'); }
            catch (_) { return; }
            await this._deleteCurrentDashboard(tab.id);
        },

        async deleteCurrentDashboard() {
            if (this.dashboards.length <= 1) return;
            try { await window.confirmDialog('Delete this dashboard and all its cards?', 'Delete'); }
            catch (_) { return; }
            await this._deleteCurrentDashboard(this.dashboardId);
        },

        async _deleteCurrentDashboard(dashId) {
            const url  = this.urlDashboards.replace(/\/$/, '') + '/' + dashId + '/';
            const resp = await this._deleteReq(url);
            if (!resp.ok) return;

            // Navigate to another dashboard
            const remaining = this.dashboards.filter(d => d.id !== dashId);
            if (remaining.length > 0) {
                window.location.href = this._tabUrl(remaining[0]);
            }
        },

        // ── Mobile swipe between dashboards ──────────────────────────────────
        onGridTouchStart(e) {
            if (e.touches.length !== 1) return;
            this._swipeStartX = e.touches[0].clientX;
            this._swipeStartY = e.touches[0].clientY;
        },

        onGridTouchMove(e) {
            // If a resize or card-drag is active, don't swipe
            if (this._resizeState || this.touchDragging) return;
        },

        onGridTouchEnd(e) {
            if (this._swipeStartX === null) return;
            if (this.touchDragging) { this._swipeStartX = null; return; }

            const dx = (e.changedTouches[0]?.clientX ?? 0) - this._swipeStartX;
            const dy = (e.changedTouches[0]?.clientY ?? 0) - this._swipeStartY;
            this._swipeStartX = null;

            // Only count horizontal-dominant swipes > 60px
            if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;

            const idx = this.dashboards.findIndex(d => d.id === this.dashboardId);
            if (dx < 0 && idx < this.dashboards.length - 1) {
                // Swipe left → next dashboard
                window.location.href = this._tabUrl(this.dashboards[idx + 1]);
            } else if (dx > 0 && idx > 0) {
                // Swipe right → previous dashboard
                window.location.href = this._tabUrl(this.dashboards[idx - 1]);
            }
        },

        // ── Mobile edge-drag card between dashboards ──────────────────────────
        // Touch events on cards fire through the card element; we capture them
        // on the grid to detect edge proximity.
        _startTouchCardDrag(cardId) {
            this.touchDragging      = true;
            this._touchDragCardId   = cardId;
            this.isMobileEdgeActive = true;
            this.touchEdge          = null;
        },

        _endTouchCardDrag() {
            clearTimeout(this._touchEdgeTimer);
            this.touchDragging      = false;
            this.isMobileEdgeActive = false;
            this.touchEdge          = null;
            this._touchDragCardId   = null;
        },

        async _moveTouchCardToDashboard(tabId) {
            const cardId = this._touchDragCardId;
            if (!cardId) return;
            const url = this.urlCards.split('?')[0].replace(/\/$/, '') + '/' + cardId + '/';
            await this._patchJson(url, { dashboard_id: tabId });
            this.cards = this.cards.filter(c => c.id !== cardId);
        },

        // ── Move card to dashboard via edit modal ─────────────────────────────
        async moveCardToDashboard(cardId, dashId) {
            if (!cardId || !dashId) return;
            dashId = parseInt(dashId, 10);
            if (dashId === this.dashboardId) return;

            const url  = this.urlCards.split('?')[0].replace(/\/$/, '') + '/' + cardId + '/';
            const resp = await this._patchJson(url, { dashboard_id: dashId });
            if (!resp.ok) return;

            this.editCard = null;
            this.cards = this.cards.filter(c => c.id !== cardId);
        },

        // ── Resize (pointer events on the handle) ─────────────────────────────
        onResizeStart(cardId, e) {
            e.stopPropagation();
            e.preventDefault();
            const colW = this._colW || 130;
            const rowH = this._rowH || 130;
            const card = this.cards.find(c => c.id === cardId);
            if (!card) return;

            const mob = this._isMobile();
            this._resizeState = {
                cardId,
                startX: e.clientX,
                startY: e.clientY,
                startW: mob ? (card.mobile_width  ?? card.width)  : card.width,
                startH: mob ? (card.mobile_height ?? card.height) : card.height,
                colW,
                rowH,
                mobile: mob,
            };
            e.target.setPointerCapture(e.pointerId);
        },

        onResizeMove(cardId, e) {
            const s = this._resizeState;
            if (!s || s.cardId !== cardId) return;

            const dx      = e.clientX - s.startX;
            const dy      = e.clientY - s.startY;
            const maxCols = this._currentCols || 12;
            const newW    = Math.max(1, Math.min(maxCols, s.startW + Math.round(dx / s.colW)));
            const newH    = Math.max(1, s.startH + Math.round(dy / s.rowH));

            const card = this.cards.find(c => c.id === cardId);
            if (card) {
                if (s.mobile) {
                    card.mobile_width  = newW;
                    card.mobile_height = newH;
                } else {
                    card.width  = newW;
                    card.height = newH;
                }
            }
        },

        async onResizeEnd(cardId, e) {
            const s = this._resizeState;
            if (!s || s.cardId !== cardId) return;
            this._resizeState = null;

            const card = this.cards.find(c => c.id === cardId);
            if (!card) return;

            const w = s.mobile ? card.mobile_width  : card.width;
            const h = s.mobile ? card.mobile_height : card.height;

            const baseUrl = this.urlCards.split('?')[0];
            const resp = await this._patchJson(
                baseUrl.replace(/\/$/, '') + '/' + cardId + '/resize/',
                { width: w, height: h, mobile: s.mobile },
            );
            const data = await resp.json();
            if (data.yaml_config) card.yaml_config = data.yaml_config;
            if (s.mobile) {
                if (data.mobile_width  != null) card.mobile_width  = data.mobile_width;
                if (data.mobile_height != null) card.mobile_height = data.mobile_height;
            } else {
                if (data.width  != null) card.width  = data.width;
                if (data.height != null) card.height = data.height;
            }

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
                const baseUrl = this.urlCards.split('?')[0];
                const resp = await this._patchJson(
                    baseUrl.replace(/\/$/, '') + '/' + this.editCard.id + '/',
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
            const baseUrl = this.urlCards.split('?')[0];
            await this._deleteReq(baseUrl.replace(/\/$/, '') + '/' + cardId + '/');
            this.editCard = null;
            await this.fetchCards();
        },

        async resetDashboard() {
            try { await window.confirmDialog('Reset dashboard to defaults? All cards will be replaced.', 'Reset'); } catch (_) { return; }
            const resp = await this._postJson(this.urlReset, { dashboard_id: this.dashboardId });
            if (!resp.ok) return;
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
                const baseUrl = this.urlCards.split('?')[0];
                const resp = await this._postJson(baseUrl, {
                    yaml_config:  this.addYaml,
                    dashboard_id: this.dashboardId,
                });
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

        // ── HTTP helpers ──────────────────────────────────────────────────────
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

        // ── Value formatters ──────────────────────────────────────────────────
        formatValue(val) {
            if (val === null || val === undefined) return '–';
            const n = parseFloat(val);
            if (isNaN(n)) return String(val);
            return Math.round(n).toString();
        },

        cellText(card) {
            const val = this.formatValue(card.data && card.data.value);
            const tpl = (card.config && card.config.template) || '$VALUE $CURRENCY_SYMBOL';
            return tpl.replace('$VALUE', val).replace('$CURRENCY_SYMBOL', this.currency);
        },

        listTypeAbbr(type) {
            return TYPE_ABBR[type] || (type || '').substring(0, 2).toUpperCase();
        },

        listSumText(card) {
            const val = card.data && card.data.sum_value;
            if (val === null || val === undefined) return '';
            const rounded = Math.round(parseFloat(val));
            const tpl = (card.config && card.config.sum_template) || '$VALUE $CURRENCY_SYMBOL';
            return tpl.replace('$VALUE', rounded.toString()).replace('$CURRENCY_SYMBOL', this.currency);
        },

        listSumColorClass(card) {
            if (!card.config || card.config.type_colors === false) return '';
            if (card.config.method === 'count') return '';
            const val = card.data && card.data.sum_value;
            if (val === null || val === undefined) return '';
            const n = parseFloat(val);
            if (isNaN(n)) return '';
            if (n > 0) return 'dash-list-sum--positive';
            if (n < 0) return 'dash-list-sum--negative';
            return '';
        },

        cardColorStyle(cfg, value) {
            const dark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            let color = dark
                ? (cfg.color_darkmode  || cfg.color)
                : (cfg.color_lightmode || cfg.color);

            let bpTextColor = '';
            const bps = cfg && cfg.color_breakpoints;
            if (bps && bps.length && value !== null && value !== undefined) {
                const num = parseFloat(value);
                if (!isNaN(num)) {
                    for (const bp of bps) {
                        if (num < bp.less_than) {
                            const bpColor = dark
                                ? (bp.color_darkmode  || bp.color)
                                : (bp.color_lightmode || bp.color);
                            if (bpColor) color = bpColor;
                            const tc = dark
                                ? (bp.text_color_darkmode  || bp.text_color)
                                : (bp.text_color_lightmode || bp.text_color);
                            if (tc) bpTextColor = tc;
                        }
                    }
                }
            }

            if (!color) return '';

            const textColor = bpTextColor
                || (dark
                    ? (cfg.text_color_darkmode  || cfg.text_color || 'white')
                    : (cfg.text_color_lightmode || cfg.text_color || 'black'));

            return `background:${color};color:${textColor}`;
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.store('sharing', {
        mode: localStorage.getItem('sharingMode') || 'personal',
        set(mode) {
            this.mode = mode;
            localStorage.setItem('sharingMode', mode);
        },
    });
    Alpine.data('dashboardBoard', dashboardBoard);
});

Alpine.start();
