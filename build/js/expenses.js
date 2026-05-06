import Alpine from 'alpinejs';

function expenseList() {
    return {
        expenses: [],
        query: '',
        pending: false,
        fetching: false,
        selected: {},
        bulkAction: '',
        csrf: '',
        _debounceTimer: null,
        _xhr: null,

        apiUrl: '',
        periodYear: '',
        periodMonth: '',
        periodMode: '',
        currency: '',
        urlEdit: '',
        urlClone: '',
        urlDelete: '',
        urlExpenses: '',
        urlBulkAction: '',
        urlExport: '',
        exportHref: '',

        init() {
            const cfg = window.EXPENSE_CONFIG;
            this.apiUrl       = cfg.apiUrl;
            this.periodYear   = cfg.year;
            this.periodMonth  = cfg.month;
            this.periodMode   = cfg.mode;
            this.currency     = cfg.currency;
            this.urlEdit      = cfg.urlEdit;
            this.urlClone     = cfg.urlClone;
            this.urlDelete    = cfg.urlDelete;
            this.urlExpenses  = cfg.urlExpenses;
            this.urlBulkAction = cfg.urlBulkAction;
            this.urlExport    = cfg.urlExport;
            this.csrf = document.querySelector('meta[name="csrf-token"]').content;
            this.exportHref = this.periodMode === 'year'
                ? this.urlExport + '?view=year&year=' + this.periodYear
                : this.urlExport + '?year=' + this.periodYear + '&month=' + this.periodMonth;

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
            this.fetchExpenses();
        },

        onInput() {
            sessionStorage.setItem('expSearch', this.query);
            this.pending = true;
            clearTimeout(this._debounceTimer);
            this._debounceTimer = setTimeout(() => {
                this.pending = false;
                this.fetchExpenses();
            }, 200);
        },

        fetchExpenses() {
            if (this._xhr) { this._xhr.abort(); }
            this.fetching = true;
            const p = new URLSearchParams({ year: this.periodYear });
            if (this.periodMode === 'year') {
                p.set('view', 'year');
            } else {
                p.set('month', this.periodMonth);
            }
            if (this.query) p.set('q', this.query);

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

        get visibleSum() {
            if (!this.expenses.length) return '–';
            const total = this.expenses.reduce((acc, e) => {
                const v = parseFloat(e.value) || 0;
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

        editUrl(id)   { return this.urlEdit.replace('/1/',   '/' + id + '/'); },
        cloneUrl(id)  { return this.urlClone.replace('/1/',  '/' + id + '/'); },
        deleteUrl(id) { return this.urlDelete.replace('/1/', '/' + id + '/'); },

        backUrl() {
            return this.periodMode === 'year'
                ? this.urlExpenses + '?year=' + this.periodYear + '&view=year'
                : this.urlExpenses + '?year=' + this.periodYear + '&month=' + this.periodMonth;
        },

        encodedBackUrl() { return encodeURIComponent(this.backUrl()); },

        tagStr(exp) { return (exp.tags || []).map(t => t.title.toLowerCase()).join('|'); },
        catStr(exp) { return exp.category ? exp.category.title.toLowerCase() : ''; },

        submitBulk() {
            const action = this.bulkAction;
            if (!action) { alert('Bitte eine Aktion auswählen.'); return; }
            const ids = this.selectedIds;
            if (!ids.length) { alert('Keine Einträge ausgewählt.'); return; }
            const labels = { settle: 'Settle', unsettle: 'Unsettle', delete: 'Delete' };
            const label = labels[action] || action;
            const count = ids.length;
            window.confirmDialog(label + ' ' + count + ' expense' + (count !== 1 ? 's' : '') + '?', label)
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
    };
}

document.addEventListener('alpine:init', () => {
    Alpine.data('expenseList', expenseList);
});

Alpine.start();
