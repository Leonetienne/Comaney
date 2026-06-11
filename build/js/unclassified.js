import Alpine from 'alpinejs';

function sameIdSet(a, b) {
    if (a.length !== b.length) return false;
    const sa = [...a].sort((x, y) => x - y);
    const sb = [...b].sort((x, y) => x - y);
    return sa.every((v, i) => v === sb[i]);
}

function unclassifiedPage() {
    return {
        rows: [],
        categories: [],
        tags: [],
        csrf: '',
        urls: {},
        error: '',
        aiBusy: false,
        aiProgress: '',
        showAiCost: false,
        aiUnavailable: false,
        resolveAllRunning: false,
        resolveAllStopRequested: false,
        resolveAllProgress: '',
        resolveAllTotalCost: 0,
        _dismissCostPreview: null,
        _resizeTable: null,
        _repositionColHandles: null,

        init() {
            const cfg = window.UNCLASSIFIED_CONFIG;
            this.csrf = document.querySelector('meta[name="csrf-token"]').content;
            this.categories = cfg.categories || [];
            this.tags = cfg.tags || [];
            this.urls = {
                save:        uid => cfg.urlSave.replace('/0/', `/${uid}/`),
                aiSolve:     uid => cfg.urlAiSolve.replace('/0/', `/${uid}/`),
                saveAll:     cfg.urlSaveAll,
                editExpense: uid => cfg.urlEditExpense.replace('/0/', `/${uid}/`),
                editOverlay: uid => cfg.urlEditOverlay.replace('/0/', `/${uid}/`),
            };
            this.rows = (cfg.rows || []).map(r => this._augmentRow(r));
            this.$nextTick(() => this._setupColResize());

            window.addEventListener('beforeunload', e => {
                if (!this.anyDirty()) return;
                e.preventDefault();
                e.returnValue = '';
            });
        },

        _augmentRow(r) {
            return {
                ...r,
                pendingCategoryUid: r.category_uid,
                pendingCategoryTitle: r.category_title,
                pendingTagUids: [...r.tag_uids],
                pendingTagTitles: [...r.tag_titles],
                editingCategory: false,
                editingTags: false,
                tagInput: '',
                aiUsed: false,
                aiSuggested: false,
                saving: false,
            };
        },

        isDirty(row) {
            if (row.aiSuggested) return true;
            if (row.pendingCategoryUid !== row.category_uid) return true;
            return !sameIdSet(row.pendingTagUids, row.tag_uids);
        },

        anyDirty() {
            return this.rows.some(r => this.isDirty(r));
        },

        // Per-value highlight: only true when there's an actual new value to
        // show (unlike isDirty(), doesn't fire just because an AI suggestion
        // came back with nothing to change in this particular field). Tags
        // are highlighted per-tag in the template (only the new ones), not
        // via a whole-cell check like this.
        categoryDirty(row) {
            return row.pendingCategoryUid !== row.category_uid;
        },

        // ── Column resize: drag handles span the FULL table height, not just
        // the header row. They're plain DOM elements injected once after the
        // table mounts (not Alpine-templated) since their position tracks
        // live pixel measurements during a drag, which isn't something
        // Alpine's reactive-property tracking has any reason to see. ───────
        _setupColResize() {
            const wrap = this.$refs.tableWrap;
            const table = this.$refs.table;
            if (!wrap || !table) return;
            this._resizeTable = table;

            const boundaryCount = table.querySelectorAll('thead th').length - 1;
            const handles = [];
            for (let i = 0; i < boundaryCount; i++) {
                const handle = document.createElement('div');
                handle.className = 'col-resize-handle-full';
                handle.addEventListener('mousedown', e => this.startColResize(e, i));
                wrap.appendChild(handle);
                handles.push(handle);
            }

            const reposition = () => {
                const ths = table.querySelectorAll('thead th');
                const wrapRect = wrap.getBoundingClientRect();
                handles.forEach((h, i) => {
                    const r = ths[i].getBoundingClientRect();
                    h.style.left = `${r.right - wrapRect.left}px`;
                    h.style.height = `${table.getBoundingClientRect().height}px`;
                });
            };
            reposition();
            this._repositionColHandles = reposition;
            new ResizeObserver(reposition).observe(table);
        },

        startColResize(event, colIndex) {
            event.preventDefault();
            const table = this._resizeTable;
            if (!table) return;
            const cols = table.querySelectorAll('colgroup col');
            // <col> elements don't reliably report a layout box across
            // browsers; measure the <th> cells instead (they always have
            // one) and apply the result to the <col> widths, which is what
            // table-layout:fixed actually keys off.
            const headerCells = table.querySelectorAll('thead th');
            const startX = event.clientX;
            const startWidths = Array.from(headerCells).map(c => c.getBoundingClientRect().width);
            const minWidth = 60;

            const onMove = e => {
                const delta = e.clientX - startX;
                const left = Math.max(minWidth, startWidths[colIndex] + delta);
                const right = Math.max(minWidth, startWidths[colIndex + 1] - delta);
                cols[colIndex].style.width = `${left}px`;
                cols[colIndex + 1].style.width = `${right}px`;
                if (this._repositionColHandles) this._repositionColHandles();
            };
            const onUp = () => {
                document.removeEventListener('mousemove', onMove);
                document.removeEventListener('mouseup', onUp);
            };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        },

        updateBadgeCount(delta) {
            const link = document.querySelector(`.sidebar a[href="${window.location.pathname}"]`);
            const badge = link && link.querySelector('.action-badge');
            if (!badge) return;
            const n = Math.max(0, parseInt(badge.textContent, 10) - delta);
            if (n <= 0) badge.remove(); else badge.textContent = n;
        },

        // ── Category cell ────────────────────────────────────────────────
        openCategoryEditor(row) {
            row.editingCategory = true;
        },

        onCategoryChange(row, uidStr) {
            const uid = uidStr ? parseInt(uidStr, 10) : null;
            const cat = this.categories.find(c => c.uid === uid);
            row.pendingCategoryUid = cat ? cat.uid : null;
            row.pendingCategoryTitle = cat ? cat.title : null;
            row.editingCategory = false;
        },

        // ── Tags cell ─────────────────────────────────────────────────────
        openTagsEditor(row) {
            row.editingTags = true;
        },

        closeTagsEditor(row) {
            row.editingTags = false;
            row.tagInput = '';
        },

        tagSuggestions(row) {
            const q = row.tagInput.trim().toLowerCase();
            if (!q) return [];
            const selected = new Set(row.pendingTagUids);
            return this.tags
                .filter(t => !selected.has(t.uid) && t.title.toLowerCase().includes(q))
                .slice(0, 8);
        },

        addTag(row, tag) {
            if (!row.pendingTagUids.includes(tag.uid)) {
                row.pendingTagUids.push(tag.uid);
                row.pendingTagTitles.push(tag.title);
            }
            row.tagInput = '';
        },

        removeTag(row, uid) {
            const idx = row.pendingTagUids.indexOf(uid);
            if (idx === -1) return;
            row.pendingTagUids.splice(idx, 1);
            row.pendingTagTitles.splice(idx, 1);
        },

        // ── Edit / Revert / Save ─────────────────────────────────────────
        editRow(row) {
            const base = row.kind === 'own' ? this.urls.editExpense(row.expense_uid) : this.urls.editOverlay(row.expense_uid);
            window.location.href = `${base}?back=${encodeURIComponent(window.location.pathname)}`;
        },

        revertRow(row) {
            row.pendingCategoryUid = row.category_uid;
            row.pendingCategoryTitle = row.category_title;
            row.pendingTagUids = [...row.tag_uids];
            row.pendingTagTitles = [...row.tag_titles];
            row.aiSuggested = false;
            row.editingCategory = false;
            row.editingTags = false;
            row.tagInput = '';
        },

        _mergeSavedRow(row, saved) {
            const resolved = saved.problem === null || saved.problem === undefined;
            if (resolved) {
                this.rows = this.rows.filter(r => r.expense_uid !== row.expense_uid);
                this.updateBadgeCount(1);
                return;
            }
            Object.assign(row, {
                category_uid: saved.category_uid,
                category_title: saved.category_title,
                tag_uids: saved.tag_uids,
                tag_titles: saved.tag_titles,
                problem: saved.problem,
                pendingCategoryUid: saved.category_uid,
                pendingCategoryTitle: saved.category_title,
                pendingTagUids: [...saved.tag_uids],
                pendingTagTitles: [...saved.tag_titles],
                aiSuggested: false,
                aiUsed: false,
                editingCategory: false,
                editingTags: false,
            });
        },

        async saveRow(row) {
            if (row.saving) return;
            row.saving = true;
            this.error = '';
            try {
                const res = await fetch(this.urls.save(row.expense_uid), {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
                    body: JSON.stringify({ category_uid: row.pendingCategoryUid, tag_uids: row.pendingTagUids }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) { this.error = data.error || 'Could not save.'; return; }
                this._mergeSavedRow(row, data.row);
            } finally {
                row.saving = false;
            }
        },

        async saveAll() {
            const dirtyRows = this.rows.filter(r => this.isDirty(r));
            if (!dirtyRows.length) return;
            this.aiBusy = true;
            this.aiProgress = 'Saving...';
            this.error = '';
            try {
                const res = await fetch(this.urls.saveAll, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
                    body: JSON.stringify({
                        rows: dirtyRows.map(r => ({
                            expense_uid: r.expense_uid,
                            category_uid: r.pendingCategoryUid,
                            tag_uids: r.pendingTagUids,
                        })),
                    }),
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) { this.error = data.error || 'Could not save all.'; return; }
                for (const saved of data.rows) {
                    const row = this.rows.find(r => r.expense_uid === saved.expense_uid);
                    if (row) this._mergeSavedRow(row, saved);
                }
            } finally {
                this.aiBusy = false;
                this.aiProgress = '';
            }
        },

        // ── AI solve ──────────────────────────────────────────────────────
        // Returns the call's cost in cents on success, or null on failure
        // (this.error is set either way a request completes with an error).
        // A 402 means the AI framework itself blocked the call (trial/budget
        // exhausted, verified server-side in AIService.__init__) -- flips
        // aiUnavailable so every AI button on the page disappears, without
        // touching any row's already-applied pending changes.
        async _requestAiSolve(row) {
            const res = await fetch(this.urls.aiSolve(row.expense_uid), {
                method: 'POST',
                headers: { 'X-CSRFToken': this.csrf },
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (res.status === 402) {
                    this.aiUnavailable = true;
                    this.error = data.error || 'AI budget exhausted. AI features are no longer available for this account.';
                } else {
                    this.error = data.error || 'AI suggestion failed.';
                }
                return null;
            }
            if (row.category_uid === null) {
                row.pendingCategoryUid = data.category_uid ?? null;
                row.pendingCategoryTitle = data.category_title ?? null;
            }
            if (!row.tag_uids.length) {
                row.pendingTagUids = data.tag_uids || [];
                row.pendingTagTitles = data.tag_titles || [];
            }
            row.aiUsed = true;
            row.aiSuggested = true;
            return typeof data.cost_cents === 'number' ? data.cost_cents : 0;
        },

        // Lets a click on the overlay skip the rest of the cost-preview wait.
        dismissCostPreview() {
            if (this._dismissCostPreview) {
                this._dismissCostPreview();
                this._dismissCostPreview = null;
            }
        },

        async aiSolveRow(row) {
            if (this.aiBusy || row.saving) return;
            this.aiBusy = true;
            this.showAiCost = false;
            this.aiProgress = `Thinking about "${row.title}"...`;
            this.error = '';
            try {
                const costCents = await this._requestAiSolve(row);
                if (costCents !== null) {
                    // Briefly show what this one call cost before the
                    // overlay fades out. The box itself has a fixed size
                    // (see .unclassified-block-box) so this swap never
                    // reflows/shrinks it. Clicking the overlay dismisses it
                    // immediately instead of waiting out the full delay.
                    this.aiProgress = `AI Cost:\n${costCents.toFixed(1)} ¢`;
                    this.showAiCost = true;
                    await new Promise(resolve => {
                        this._dismissCostPreview = resolve;
                        setTimeout(resolve, 1250);
                    });
                    this._dismissCostPreview = null;
                }
            } finally {
                this.aiBusy = false;
                this.aiProgress = '';
                this.showAiCost = false;
            }
        },

        stopResolveAll() {
            this.resolveAllStopRequested = true;
        },

        async aiResolveAll() {
            if (this.resolveAllRunning) return;
            const targets = this.rows.filter(r => !this.isDirty(r));
            if (!targets.length) return;
            this.resolveAllRunning = true;
            this.resolveAllStopRequested = false;
            this.resolveAllTotalCost = 0;
            this.error = '';
            let done = 0;
            for (const row of targets) {
                if (this.resolveAllStopRequested) break;
                // Re-check: a manual edit elsewhere on the page since the
                // batch started may have made this row dirty in the meantime.
                if (this.isDirty(row)) { done += 1; continue; }
                this.resolveAllProgress = `Resolving ${done + 1} of ${targets.length}...`;
                const costCents = await this._requestAiSolve(row);
                if (costCents === null) {
                    this.error = `${this.error} (stopped after ${done} of ${targets.length})`.trim();
                    break;
                }
                this.resolveAllTotalCost += costCents;
                done += 1;
            }
            this.resolveAllRunning = false;
            this.resolveAllProgress = '';
        },
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('unclassifiedPage', unclassifiedPage);
});

Alpine.start();
