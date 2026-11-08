// "Enter manually" share dialog for the expense, recurring expense and AI Express forms.
// openShareDialog({rows: [{key, name, avatarHtml, share, removable}], value, currency})
// resolves {shares: {key: percent}, removed: [key]} on Save, null on cancel.

// shares are stored with 3 decimals
const TOLERANCE = 0.001;

const RESET_ICON = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.5 10a6.5 6.5 0 1 0 2-4.7"/><path d="M3.5 3v3.5H7"/></svg>';
const REMOVE_ICON = '<svg viewBox="0 0 20 20" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15"/></svg>';

const round = (n, d) => Math.round(n * 10 ** d) / 10 ** d;

function parseNumber(text) {
    const t = String(text).trim().replace(',', '.');
    if (t === '') return null;
    const n = Number(t);
    return Number.isFinite(n) ? n : NaN;
}

function formatPct(n) {
    return String(round(n, 3));
}

// whole percent; "<1 %" keeps a tiny remainder from reading as 0
function hintPct(n) {
    return (Math.round(n) === 0 ? '<1' : String(Math.round(n))) + ' %';
}

function isInvalid(r) {
    return Number.isNaN(r.share) || r.share < 0 || r.share > 100;
}

function plural(n, word) {
    return n + ' ' + word + (n === 1 ? '' : 's');
}

function pctToAmount(pct, value) {
    return round(pct * value / 100, 2);
}

function amountToPct(amount, value) {
    return round(amount / value * 100, 3);
}

/** Rows with share null are empty; fills them with equal parts of what the others leave, summing to exactly 100. */
function fillRemaining(rows) {
    if (rows.some(isInvalid)) return false;
    const empty = rows.filter(r => r.share === null);
    const rest = round(100 - rows.reduce((a, r) => a + (r.share ?? 0), 0), 3);
    if (!empty.length || rest < -TOLERANCE) return false;
    const per = Math.floor(Math.max(rest, 0) / empty.length * 1000) / 1000;
    empty.forEach((r, i) => {
        r.share = i === empty.length - 1 ? round(Math.max(rest, 0) - per * (empty.length - 1), 3) : per;
    });
    return true;
}

/** Text explaining why the rows can't be saved, or '' when they can. */
function saveBlockReason(rows, value, currency) {
    if (rows.some(isInvalid)) {
        return 'Shares must be numbers between 0 and 100 %';
    }
    const emptyCount = rows.filter(r => r.share === null).length;
    const rest = round(100 - rows.reduce((a, r) => a + (r.share ?? 0), 0), 3);
    const money = pct => value > 0 ? ' (' + pctToAmount(Math.abs(pct), value).toFixed(2) + ' ' + currency + ')' : '';
    const parts = [];
    if (rest < -TOLERANCE) parts.push(hintPct(-rest) + money(rest) + ' over 100 %');
    else if (rest > TOLERANCE) parts.push(hintPct(rest) + money(rest) + ' left to assign');
    if (emptyCount) parts.push(plural(emptyCount, 'empty row'));
    return parts.join(', ');
}

let dialogEl = null;

function buildDialog() {
    const el = document.createElement('div');
    el.className = 'cdialog-backdrop share-dialog-backdrop';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML =
        '<div class="cdialog share-dialog" role="dialog" aria-modal="true" aria-labelledby="share-dialog-title">' +
            '<p class="cdialog-title" id="share-dialog-title">Enter shares</p>' +
            '<div class="share-dialog-rows"></div>' +
            '<button type="button" class="btn btn-secondary btn-sm share-dialog-fill">Fill remaining shares equally</button>' +
            '<p class="share-dialog-reason" aria-live="polite"></p>' +
            '<div class="cdialog-actions">' +
                '<button type="button" class="btn share-dialog-save">Save</button>' +
                '<button type="button" class="btn btn-secondary share-dialog-cancel">Cancel</button>' +
            '</div>' +
        '</div>';
    document.body.appendChild(el);
    return el;
}

window.openShareDialog = function ({rows, value, currency}) {
    if (!dialogEl) dialogEl = buildDialog();
    const rowsEl = dialogEl.querySelector('.share-dialog-rows');
    const fillBtn = dialogEl.querySelector('.share-dialog-fill');
    const reasonEl = dialogEl.querySelector('.share-dialog-reason');
    const saveBtn = dialogEl.querySelector('.share-dialog-save');
    const cancelBtn = dialogEl.querySelector('.share-dialog-cancel');
    const hasValue = value > 0;
    const state = rows.map(r => ({...r, share: round(r.share, 3)}));
    const removed = [];
    const returnFocus = document.activeElement;

    function rowEls(r) {
        return rowsEl.querySelector('[data-key="' + CSS.escape(r.key) + '"]');
    }

    function writeFields(r) {
        const el = rowEls(r);
        el.querySelector('.share-dialog-pct').value = r.share === null || Number.isNaN(r.share) ? '' : formatPct(r.share);
        el.querySelector('.share-dialog-amt').value = hasValue && r.share !== null && !Number.isNaN(r.share)
            ? pctToAmount(r.share, value).toFixed(2) : '';
    }

    function update() {
        const reason = saveBlockReason(state, value, currency);
        reasonEl.textContent = reason;
        saveBtn.disabled = reason !== '';
        const rest = 100 - state.reduce((a, r) => a + (r.share ?? 0), 0);
        fillBtn.disabled = !state.some(r => r.share === null) || state.some(isInvalid) || rest < -TOLERANCE;
        state.forEach(r => rowEls(r).classList.toggle('share-dialog-row--invalid', isInvalid(r)));
    }

    function render() {
        rowsEl.innerHTML = '';
        state.forEach(r => {
            const row = document.createElement('div');
            row.className = 'share-dialog-row';
            row.dataset.key = r.key;
            row.innerHTML =
                '<span class="share-dialog-name">' + r.avatarHtml + '<span class="share-dialog-name-text"></span></span>' +
                '<label class="share-dialog-field"><input type="text" inputmode="decimal" class="share-dialog-pct" autocomplete="off"><span>%</span></label>' +
                '<label class="share-dialog-field"><input type="text" inputmode="decimal" class="share-dialog-amt" autocomplete="off"' + (hasValue ? '' : ' disabled') + '><span></span></label>' +
                '<button type="button" class="share-dialog-icon share-dialog-reset" title="Reset" aria-label="Reset">' + RESET_ICON + '</button>' +
                (r.removable
                    ? '<button type="button" class="share-dialog-icon share-dialog-remove" title="Remove" aria-label="Remove">' + REMOVE_ICON + '</button>'
                    : '<span class="share-dialog-icon-spacer"></span>');
            row.querySelector('.share-dialog-name-text').textContent = r.name;
            row.querySelector('.share-dialog-amt + span').textContent = currency;
            row.querySelector('.share-dialog-pct').setAttribute('aria-label', r.name + ' share in percent');
            row.querySelector('.share-dialog-amt').setAttribute('aria-label', r.name + ' share in ' + currency);
            rowsEl.appendChild(row);

            const pctIn = row.querySelector('.share-dialog-pct');
            const amtIn = row.querySelector('.share-dialog-amt');
            pctIn.addEventListener('input', () => {
                r.share = parseNumber(pctIn.value);
                amtIn.value = hasValue && r.share !== null && !Number.isNaN(r.share) ? pctToAmount(r.share, value).toFixed(2) : '';
                update();
            });
            amtIn.addEventListener('input', () => {
                const amount = parseNumber(amtIn.value);
                r.share = amount === null || Number.isNaN(amount) ? amount : amountToPct(amount, value);
                pctIn.value = r.share === null || Number.isNaN(r.share) ? '' : formatPct(r.share);
                update();
            });
            row.querySelector('.share-dialog-reset').addEventListener('click', () => {
                r.share = null;
                writeFields(r);
                update();
                pctIn.focus();
            });
            const removeBtn = row.querySelector('.share-dialog-remove');
            if (removeBtn) removeBtn.addEventListener('click', () => {
                state.splice(state.indexOf(r), 1);
                removed.push(r.key);
                if (state.length === 1) state[0].share = 100;
                render();
            });
            writeFields(r);
        });
        update();
    }

    render();
    dialogEl.classList.add('cdialog-visible');
    dialogEl.setAttribute('aria-hidden', 'false');
    const firstInput = rowsEl.querySelector('.share-dialog-pct');
    if (firstInput) firstInput.focus();

    return new Promise(resolve => {
        function close(result) {
            dialogEl.classList.remove('cdialog-visible');
            dialogEl.setAttribute('aria-hidden', 'true');
            fillBtn.removeEventListener('click', onFill);
            saveBtn.removeEventListener('click', onSave);
            cancelBtn.removeEventListener('click', onCancel);
            dialogEl.removeEventListener('click', onBackdrop);
            document.removeEventListener('keydown', onKey);
            if (returnFocus && returnFocus.focus) returnFocus.focus();
            resolve(result);
        }
        function onFill() {
            if (fillRemaining(state)) { state.forEach(writeFields); update(); }
        }
        function onSave() {
            if (saveBtn.disabled) return;
            const shares = {};
            state.forEach(r => { shares[r.key] = r.share; });
            close({shares, removed: removed.slice()});
        }
        function onCancel() { close(null); }
        function onBackdrop(e) { if (e.target === dialogEl) close(null); }
        function onKey(e) {
            if (e.key === 'Escape') { e.preventDefault(); close(null); }
            else if (e.key === 'Enter' && e.target.matches('.share-dialog-row input')) { e.preventDefault(); onSave(); }
        }
        fillBtn.addEventListener('click', onFill);
        saveBtn.addEventListener('click', onSave);
        cancelBtn.addEventListener('click', onCancel);
        dialogEl.addEventListener('click', onBackdrop);
        document.addEventListener('keydown', onKey);
    });
};
