/**
 * dateRange singleton — manages the global date range selection.
 *
 * Priority on load (highest first):
 *   1. URL params date_from + date_to
 *   2. localStorage key comaney_date_range
 *   3. Server-injected default (window.DATE_RANGE_CONFIG.defaultFrom/To)
 */

const LS_KEY = 'comaney_date_range';

const _ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

function _isValidIso(s) {
    return typeof s === 'string' && _ISO_RE.test(s);
}

function _readUrl() {
    const p = new URLSearchParams(window.location.search);
    const f = p.get('date_from');
    const t = p.get('date_to');
    if (_isValidIso(f) && _isValidIso(t)) return { from: f, to: t };
    return null;
}

function _readStorage() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (_isValidIso(parsed.from) && _isValidIso(parsed.to)) return parsed;
    } catch (_) {}
    return null;
}

function _serverDefault() {
    const cfg = window.DATE_RANGE_CONFIG;
    if (cfg && _isValidIso(cfg.defaultFrom) && _isValidIso(cfg.defaultTo)) {
        return { from: cfg.defaultFrom, to: cfg.defaultTo };
    }
    return null;
}

function _init() {
    const fromUrl = _readUrl();
    if (fromUrl) {
        // URL takes precedence; also persist to localStorage
        try { localStorage.setItem(LS_KEY, JSON.stringify(fromUrl)); } catch (_) {}
        return fromUrl;
    }
    const fromStorage = _readStorage();
    if (fromStorage) return fromStorage;
    const def = _serverDefault();
    if (def) return def;
    return { from: '', to: '' };
}

const dateRange = {
    _current: null,

    get() {
        if (!this._current) this._current = _init();
        return this._current;
    },

    set(from, to) {
        this._current = { from, to };
        try { localStorage.setItem(LS_KEY, JSON.stringify({ from, to })); } catch (_) {}

        // Update URL without page reload, preserving other params
        const url = new URL(window.location.href);
        url.searchParams.set('date_from', from);
        url.searchParams.set('date_to', to);
        history.replaceState(null, '', url.toString());

        window.dispatchEvent(new CustomEvent('daterangechange', { detail: { from, to } }));
    },

    clear() {
        const def = _serverDefault();
        if (def) {
            this.set(def.from, def.to);
        }
    },
};

export default dateRange;
