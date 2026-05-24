import Alpine from 'alpinejs';
import dateRange from './date-range.js';

// Expose singleton for the date-range-nav partial inline script
window._dateRange = dateRange;

function expenseList() {
    return {
        expenses: [],
        query: '',
        hideRecurring: false,
        sortBy: 'date',
        sortDir: 'desc',
        pending: false,
        fetching: false,
        selected: {},
        bulkAction: '',
        bulkTagId: '',
        bulkCategoryId: '',
        tags: [],
        categories: [],
        csrf: '',
        _debounceTimer: null,
        _xhr: null,

        apiUrl: '',
        dateFrom: '',
        dateTo: '',
        sharingMode: '',
        currency: '',
        urlEdit: '',
        urlEditLite: '',
        urlClone: '',
        urlDelete: '',
        urlExpenses: '',
        urlBulkAction: '',
        urlExport: '',
        exportHref: '',

        init() {
            const cfg = window.EXPENSE_CONFIG;
            this.apiUrl       = cfg.apiUrl;
            this.sharingMode  = this.$store.sharing.mode;
            this.currency     = cfg.currency;
            this.$watch('$store.sharing.mode', mode => {
                this.sharingMode = mode;
                this.fetchExpenses();
            });
            this.urlEdit      = cfg.urlEdit;
            this.urlEditLite  = cfg.urlEditLite;
            this.urlClone     = cfg.urlClone;
            this.urlDelete    = cfg.urlDelete;
            this.urlExpenses  = cfg.urlExpenses;
            this.urlBulkAction = cfg.urlBulkAction;
            this.urlExport    = cfg.urlExport;
            this.tags         = cfg.tags || [];
            this.categories   = cfg.categories || [];
            this.csrf = document.querySelector('meta[name="csrf-token"]').content;

            const cur = dateRange.get();
            this.dateFrom = cur.from;
            this.dateTo   = cur.to;
            this._updateExportHref();

            window.addEventListener('daterangechange', (e) => {
                this.dateFrom = e.detail.from;
                this.dateTo   = e.detail.to;
                this._updateExportHref();
                this.fetchExpenses();
            });

            const urlSearch = new URLSearchParams(window.location.search).get('search');
            if (urlSearch !== null) {
                sessionStorage.setItem('expSearch', urlSearch);
                this.query = urlSearch;
            } else {
                let ref = '';
                try { ref = document.referrer ? new URL(document.referrer).pathname : ''; } catch(e) {}
                const expBase = this.urlExpenses.replace(/\/$/, '');
                const fromExpArea = ref === expBase + '/' || ref.startsWith(expBase + '/');
                if (fromExpArea) {
                    const saved = sessionStorage.getItem('expSearch');
                    if (saved) { this.query = saved; }
                } else {
                    sessionStorage.removeItem('expSearch');
                }
            }
            this._syncHideRecurring();
            this.fetchExpenses();
        },

        onInput() {
            sessionStorage.setItem('expSearch', this.query);
            this._syncHideRecurring();
            this.pending = true;
            clearTimeout(this._debounceTimer);
            this._debounceTimer = setTimeout(() => {
                this.pending = false;
                this.fetchExpenses();
            }, 200);
        },

        _syncHideRecurring() {
            const m = this.query.toLowerCase().match(/\brecurring=(yes|true|1|no|false|0)\b/);
            if (m) {
                const v = m[1];
                this.hideRecurring = v === 'no' || v === 'false' || v === '0';
            } else {
                this.hideRecurring = false;
            }
        },

        onHideRecurringChange() {
            let q = this.query.replace(/\brecurring=\S+/gi, '').replace(/\s{2,}/g, ' ').trim();
            if (this.hideRecurring) {
                q = q ? q + ' recurring=no' : 'recurring=no';
            }
            this.query = q;
            sessionStorage.setItem('expSearch', this.query);
            this.pending = true;
            clearTimeout(this._debounceTimer);
            this._debounceTimer = setTimeout(() => {
                this.pending = false;
                this.fetchExpenses();
            }, 200);
        },

        _updateExportHref() {
            this.exportHref = this.urlExport
                + '?date_from=' + encodeURIComponent(this.dateFrom)
                + '&date_to='   + encodeURIComponent(this.dateTo);
        },

        fetchExpenses() {
            if (this._xhr) { this._xhr.abort(); }
            this.fetching = true;
            const p = new URLSearchParams();
            p.set('date_from', this.dateFrom);
            p.set('date_to',   this.dateTo);
            if (this.query) p.set('q', this.query);
            if (this.sharingMode === 'shared') p.set('sharing', 'shared');
            p.set('sort_by', this.sortBy);
            p.set('sort_dir', this.sortDir);

            const xhr = new XMLHttpRequest();
            this._xhr = xhr;
            xhr.open('GET', this.apiUrl + '?' + p.toString(), true);
            xhr.onload = () => {
                this._xhr = null;
                if (xhr.status === 200) {
                    try {
                        const data = JSON.parse(xhr.responseText);
                        this.expenses = data.expenses || [];
                        this.selected = {};
                    } catch(e) {}
                }
                // defer until after x-for has re-rendered, so data-search-loading
                // is only removed once the filtered cards are in the DOM
                Alpine.nextTick(() => { this.fetching = false; });
            };
            xhr.onerror = () => { this._xhr = null; this.fetching = false; };
            xhr.onabort = () => { this._xhr = null; };
            xhr.send();
        },

        expValue(e) {
            // In shared mode, use effective_value if available.
            const raw = (this.sharingMode === 'shared' && e.effective_value != null)
                ? e.effective_value : e.value;
            return Math.round((parseFloat(raw) || 0) * 100) / 100;
        },

        get visibleSum() {
            if (!this.expenses.length) return '–';
            const total = this.expenses.reduce((acc, e) => {
                const v = this.expValue(e);
                return acc + ((e.type === 'expense' || e.type === 'savings_dep') ? -v : v);
            }, 0);
            return total.toFixed(2);
        },

        get allSelected() {
            return this.expenses.length > 0 && this.expenses.every(e => this.selected[e.id]);
        },

        toggleSelectAll() {
            if (this.allSelected) {
                this.selected = {};
            } else {
                const s = {};
                this.expenses.forEach(e => { s[e.id] = true; });
                this.selected = s;
            }
        },

        toggleSelect(id) {
            const s = { ...this.selected };
            if (s[id]) { delete s[id]; } else { s[id] = true; }
            this.selected = s;
        },

        get selectedIds() {
            return Object.keys(this.selected).filter(k => this.selected[k]);
        },

        typeDisplay(type) {
            const m = {
                income:      'Income',
                expense:     'Expense',
                savings_dep: 'Savings Deposit',
                savings_wit: 'Savings Withdrawal',
                carry_over:  'Carry-Over',
            };
            return m[type] || type;
        },

        editUrl(id)     { return this.urlEdit.replace('/1/',     '/' + id + '/'); },
        editLiteUrl(id) { return this.urlEditLite.replace('/1/', '/' + id + '/'); },
        cloneUrl(id)    { return this.urlClone.replace('/1/',    '/' + id + '/'); },
        deleteUrl(id)   { return this.urlDelete.replace('/1/',   '/' + id + '/'); },

        backUrl() {
            return this.urlExpenses
                + '?date_from=' + encodeURIComponent(this.dateFrom)
                + '&date_to='   + encodeURIComponent(this.dateTo);
        },

        encodedBackUrl() { return encodeURIComponent(this.backUrl()); },

        tagStr(exp) { return (exp.tags || []).map(t => t.title.toLowerCase()).join('|'); },
        catStr(exp) { return exp.category ? exp.category.title.toLowerCase() : ''; },

        submitBulk() {
            const action = this.bulkAction;
            if (!action) { alert('Please select an action.'); return; }
            const ids = this.selectedIds;
            if (!ids.length) { alert('No expenses selected.'); return; }

            let extraName = null, extraValue = null, confirmMsg = '';
            const count = ids.length;
            const noun = count === 1 ? 'expense' : 'expenses';

            if (action === 'add-tag' || action === 'remove-tag') {
                if (!this.bulkTagId) { alert('Please select a tag.'); return; }
                const tag = this.tags.find(t => String(t.uid) === String(this.bulkTagId));
                const tagName = tag ? tag.title : '';
                extraName = 'tag_uid';
                extraValue = this.bulkTagId;
                confirmMsg = action === 'add-tag'
                    ? `Add tag "${tagName}" to ${count} ${noun}?`
                    : `Remove tag "${tagName}" from ${count} ${noun}?`;
            } else if (action === 'set-category') {
                const cat = this.categories.find(c => String(c.uid) === String(this.bulkCategoryId));
                extraName = 'category_uid';
                extraValue = this.bulkCategoryId;
                confirmMsg = cat
                    ? `Set category "${cat.title}" on ${count} ${noun}?`
                    : `Remove category from ${count} ${noun}?`;
            } else {
                const labels = { settle: 'Settle', unsettle: 'Unsettle', delete: 'Delete' };
                const label = labels[action] || action;
                confirmMsg = `${label} ${count} ${noun}?`;
            }

            window.confirmDialog(confirmMsg, action === 'delete' ? 'Delete' : 'Apply')
                .then(() => {
                    const form = document.createElement('form');
                    form.method = 'POST';
                    form.action = this.urlBulkAction;
                    const csrfInp = document.createElement('input');
                    csrfInp.type = 'hidden'; csrfInp.name = 'csrfmiddlewaretoken'; csrfInp.value = this.csrf;
                    form.appendChild(csrfInp);
                    const actionInp = document.createElement('input');
                    actionInp.type = 'hidden'; actionInp.name = 'action'; actionInp.value = action;
                    form.appendChild(actionInp);
                    if (extraName !== null) {
                        const extra = document.createElement('input');
                        extra.type = 'hidden'; extra.name = extraName; extra.value = extraValue;
                        form.appendChild(extra);
                    }
                    ids.forEach(id => {
                        const inp = document.createElement('input');
                        inp.type = 'hidden'; inp.name = 'uid'; inp.value = id;
                        form.appendChild(inp);
                    });
                    document.body.appendChild(form);
                    form.submit();
                })
                .catch(() => {});
        },

        avatarStack(participants) {
            return (participants || []).map(function(p) {
                const name = String(p.name || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
                const initials = String(p.initials || '').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const avatar = p.ppic_url
                    ? `<img src="${p.ppic_url}" class="user-avatar" title="${name}" alt="">`
                    : `<span class="user-avatar user-avatar--initials" style="background:${p.color}" title="${name}">${initials}</span>`;
                let badge = '';
                if (p.approval_state === 1) {
                    badge = '<span class="approval-badge approval-badge--approved" title="Approved">✓</span>';
                } else if (p.approval_state === 2) {
                    badge = '<span class="approval-badge approval-badge--rejected" title="Rejected">✗</span>';
                } else if (p.approval_state === 0) {
                    badge = '<span class="approval-badge approval-badge--neutral" title="No decision yet">?</span>';
                }
                return `<span class="avatar-wrap">${avatar}${badge}</span>`;
            }).join('');
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
    Alpine.data('expenseList', expenseList);
});

Alpine.start();
