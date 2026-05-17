/**
 * Buddy expense section on the expense create/edit form.
 * Config is injected by the template as window.BUDDY_EXPENSE_CONFIG.
 */
(function () {
    'use strict';

    var cfg = window.BUDDY_EXPENSE_CONFIG;
    if (!cfg) return;

    var cb              = document.getElementById('buddy-payment-cb');
    var section         = document.getElementById('buddy-payment-section');
    if (!cb || !section) return;

    var payerSel        = document.getElementById('buddy-upfront-select');
    var participantsEl  = document.getElementById('buddy-participants-checkboxes');
    var participantsRow  = participantsEl ? participantsEl.parentElement : null;
    var participantsLbl  = participantsRow ? participantsRow.querySelector('label') : null;
    var slidersEl       = document.getElementById('buddy-sliders');
    var equalBtn        = document.getElementById('buddy-equal-btn');
    var typeIn          = document.getElementById('buddy-upfront-type-input');
    var idIn            = document.getElementById('buddy-upfront-id-input');
    var jsonIn          = document.getElementById('buddy-spendings-json');
    var modeIn          = document.getElementById('buddy-mode-input');
    var groupIdIn       = document.getElementById('buddy-group-id-input');
    var noParticipantsErr = document.getElementById('buddy-no-participants-error');
    var payerNotice     = document.getElementById('buddy-payer-notice');
    var theForm         = cb.closest('form');
    var valueInput      = document.getElementById('id_value');

    var modeRadioSingle = document.getElementById('buddy-mode-single');
    var modeRadioGroup  = document.getElementById('buddy-mode-group');
    var groupSelectRow  = document.getElementById('buddy-group-select-row');
    var groupSelectEl   = document.getElementById('buddy-group-select');

    var ME_PK         = cfg.mePk;
    var ME_NAME       = (cfg.meFirstName + ' ' + cfg.meLastName).trim() || 'Me';
    var groupsData    = cfg.groupsData;
    var singleBuddies = cfg.singleBuddies;

    var existingUpfrontType = cfg.upfrontType;
    var existingUpfrontId   = cfg.upfrontId || ME_PK;
    var existingSpendings   = cfg.existingSpendings;
    var existingMode        = cfg.existingMode;
    var existingGroupId     = cfg.existingGroupId;
    var buddySummaryUrl     = cfg.urlBuddySummary;

    var currentMode    = 'single';
    var currentGroupId = null;
    var participants   = [];
    var _skipPayerConfirm = false;

    // ── Mode switching ─────────────────────────────────────────────────────

    if (modeRadioSingle) {
        modeRadioSingle.addEventListener('change', function () { if (this.checked) switchMode('single'); });
        modeRadioGroup.addEventListener('change',  function () { if (this.checked) switchMode('group'); });
    }
    if (groupSelectEl) {
        groupSelectEl.addEventListener('change', function () {
            currentGroupId = parseInt(this.value);
            groupIdIn.value = this.value;
            buildPayerOptions();
            buildParticipantCheckboxes(true);
            refreshParticipantCheckboxes();
            rebuildSliders();
        });
    }

    function updateParticipantsLabel() {
        if (participantsLbl) {
            participantsLbl.textContent = currentMode === 'single'
                ? 'Buddy (sharing the cost)'
                : 'Participants (sharing the cost)';
        }
    }

    function switchMode(mode) {
        currentMode = mode;
        modeIn.value = mode;
        if (mode === 'group') {
            if (groupSelectRow) groupSelectRow.style.display = 'block';
            if (groupSelectEl && groupSelectEl.value) {
                currentGroupId = parseInt(groupSelectEl.value);
                groupIdIn.value = groupSelectEl.value;
            }
        } else {
            if (groupSelectRow) groupSelectRow.style.display = 'none';
            currentGroupId = null;
            groupIdIn.value = '';
        }
        updateParticipantsLabel();
        buildPayerOptions();
        buildParticipantCheckboxes(mode === 'group');
        refreshParticipantCheckboxes();
        rebuildSliders();
    }

    // ── Build payer options ────────────────────────────────────────────────

    function buildPayerOptions() {
        var prevVal = payerSel.value;
        payerSel.innerHTML = '';
        var opts = [];
        if (currentMode === 'single') {
            opts.push({value: 'me:' + ME_PK, text: 'Me (' + ME_NAME + ')'});
            singleBuddies.forEach(function (b) {
                if (b.type === 'feuser') {
                    opts.push({value: 'feuser:' + b.id, text: b.name + (b.email ? ' (' + b.email + ')' : '')});
                } else {
                    opts.push({value: 'dummy:' + b.id, text: b.name});
                }
            });
        } else {
            var grp = groupsData.find(function (g) { return g.id === currentGroupId; });
            if (grp) {
                grp.members.forEach(function (m) {
                    var prefix = m.is_me ? 'me' : m.type;
                    var vid    = m.is_me ? ME_PK : m.id;
                    var label  = m.is_me ? 'Me (' + m.name + ')' : m.name;
                    opts.push({value: prefix + ':' + vid, text: label});
                });
            }
        }
        opts.forEach(function (o) {
            var el = document.createElement('option');
            el.value = o.value;
            el.textContent = o.text;
            payerSel.appendChild(el);
        });
        if (Array.from(payerSel.options).some(function (o) { return o.value === prevVal; })) {
            payerSel.value = prevVal;
        }
        var parts = payerSel.value.split(':');
        typeIn.value = parts[0];
        idIn.value   = parts[1];
        updatePayerNotice();
    }

    // ── Build participant checkboxes ───────────────────────────────────────
    // Me is never rendered as a checkbox; auto-add logic handles it.

    function buildParticipantCheckboxes(preCheckAll) {
        participantsEl.innerHTML = '';
        if (currentMode === 'single') {
            var sel = document.createElement('select');
            sel.id = 'buddy-participant-select';
            var emptyOpt = document.createElement('option');
            emptyOpt.value = '';
            emptyOpt.textContent = '-- Select buddy --';
            sel.appendChild(emptyOpt);
            singleBuddies.forEach(function (item) {
                var opt = document.createElement('option');
                opt.value = item.type + ':' + item.id;
                opt.dataset.type = item.type;
                opt.dataset.id   = String(item.id);
                opt.dataset.name = item.name;
                opt.textContent  = item.name;
                sel.appendChild(opt);
            });
            sel.addEventListener('change', function () {
                syncParticipantsFromCheckboxes();
                rebuildSliders();
            });
            participantsEl.appendChild(sel);
        } else {
            var grp = groupsData.find(function (g) { return g.id === currentGroupId; });
            var items = grp ? grp.members.filter(function (m) { return !m.is_me; }) : [];
            items.forEach(function (item) {
                var lbl = document.createElement('label');
                lbl.className = 'checkbox-inline buddy-participant-cb';
                lbl.dataset.type = item.type;
                lbl.dataset.id   = String(item.id);
                lbl.dataset.name = item.name;
                var inp = document.createElement('input');
                inp.type = 'checkbox';
                if (preCheckAll) inp.checked = true;
                inp.addEventListener('change', function () {
                    syncParticipantsFromCheckboxes();
                    rebuildSliders();
                });
                lbl.appendChild(inp);
                lbl.appendChild(document.createTextNode(' ' + item.name));
                participantsEl.appendChild(lbl);
            });
        }
    }

    // ── Payer notice ───────────────────────────────────────────────────────

    function updatePayerNotice() {
        if (!payerNotice) return;
        var payerType = payerSel.value.split(':')[0];
        if (payerType === 'dummy') {
            var name = esc(payerSel.options[payerSel.selectedIndex].text);
            payerNotice.className = 'info-box';
            payerNotice.innerHTML = '<p>Since <strong>' + name + '</strong> paid upfront, this expense won\'t appear in your regular expense list. You\'ll find it under <a href="' + buddySummaryUrl + '">Buddy Expenses</a> instead.</p>';
            payerNotice.style.display = 'block';
        } else if (payerType === 'feuser') {
            var name2 = esc(payerSel.options[payerSel.selectedIndex].text.split('(')[0].trim());
            payerNotice.className = 'warning-box';
            payerNotice.innerHTML = '<p><strong>Heads up:</strong> This expense will be recorded on <strong>' + name2 + '\'s</strong> account and will require their approval. Once saved, you won\'t be able to edit it from your account.</p>';
            payerNotice.style.display = 'block';
        } else {
            payerNotice.style.display = 'none';
        }
    }

    // ── Form submit guard ──────────────────────────────────────────────────

    theForm.addEventListener('submit', function (e) {
        if (cb.checked && participants.length === 0) {
            e.preventDefault();
            noParticipantsErr.style.display = 'block';
            return;
        }
        noParticipantsErr.style.display = 'none';
        if (!_skipPayerConfirm && cb.checked) {
            var payerType = payerSel.value.split(':')[0];
            if (payerType === 'feuser') {
                e.preventDefault();
                var name = payerSel.options[payerSel.selectedIndex].text.split('(')[0].trim();
                window.confirmDialog(
                    'This expense will be recorded on ' + name + '\'s account and requires their approval. You won\'t be able to edit it from your account afterwards.',
                    'Save'
                ).then(function () {
                    _skipPayerConfirm = true;
                    theForm.submit();
                }).catch(function () {});
            }
        }
    });

    // ── Checkbox toggle ────────────────────────────────────────────────────

    cb.addEventListener('change', function () {
        section.style.display = cb.checked ? 'block' : 'none';
        if (cb.checked) { initFromExisting(); }
    });
    if (cb.checked) { section.style.display = 'block'; initFromExisting(); }

    // ── Live amount update when expense value changes ──────────────────────

    if (valueInput) {
        valueInput.addEventListener('input', function () {
            refreshSliderDisplays();
            updatePayerRow();
        });
    }

    // ── Payer select change ────────────────────────────────────────────────

    payerSel.addEventListener('change', function () {
        var parts = payerSel.value.split(':');
        typeIn.value = parts[0];
        idIn.value   = parts[1];
        updatePayerNotice();
        refreshParticipantCheckboxes();
        rebuildSliders();
    });

    // ── Refresh after payer change ─────────────────────────────────────────

    function refreshParticipantCheckboxes() {
        var parts = payerSel.value.split(':');
        var payerType = parts[0];
        var payerId   = parts[1];
        if (currentMode === 'single') {
            // When the buddy pays, Me is the sole participant (auto-added). Hide the picker.
            var show = (payerType === 'me');
            if (participantsRow) participantsRow.style.display = show ? '' : 'none';
            var sel = document.getElementById('buddy-participant-select');
            if (!show && sel) sel.value = '';
        } else {
            if (participantsRow) participantsRow.style.display = '';
            participantsEl.querySelectorAll('.buddy-participant-cb').forEach(function (lbl) {
                var hide = (lbl.dataset.type === payerType && lbl.dataset.id === payerId);
                lbl.style.display = hide ? 'none' : 'block';
                if (hide) lbl.querySelector('input').checked = false;
            });
        }
        participants = [];
        syncParticipantsFromCheckboxes();
    }

    function syncParticipantsFromCheckboxes() {
        var payerType = payerSel.value.split(':')[0];
        var checked = [];
        if (payerType !== 'me') {
            var existingMe = participants.find(function (p) { return p.type === 'feuser' && p.id === ME_PK; });
            checked.push({type: 'feuser', id: ME_PK, name: ME_NAME, share: existingMe ? existingMe.share : 0});
            if (currentMode !== 'single') {
                participantsEl.querySelectorAll('.buddy-participant-cb').forEach(function (lbl) {
                    if (lbl.style.display === 'none') return;
                    var inp = lbl.querySelector('input');
                    if (inp.checked) {
                        var existing = participants.find(function (p) {
                            return p.type === lbl.dataset.type && String(p.id) === lbl.dataset.id;
                        });
                        checked.push({
                            type:  lbl.dataset.type,
                            id:    parseInt(lbl.dataset.id),
                            name:  lbl.dataset.name,
                            share: existing ? existing.share : 0,
                        });
                    }
                });
            }
        } else if (currentMode === 'single') {
            var sel = document.getElementById('buddy-participant-select');
            if (sel && sel.value) {
                var selParts = sel.value.split(':');
                var selType  = selParts[0];
                var selId    = parseInt(selParts[1]);
                var selOpt   = sel.options[sel.selectedIndex];
                var existing = participants.find(function (p) { return p.type === selType && p.id === selId; });
                checked.push({
                    type:  selType,
                    id:    selId,
                    name:  selOpt.dataset.name,
                    share: existing ? existing.share : 0,
                });
            }
        } else {
            participantsEl.querySelectorAll('.buddy-participant-cb').forEach(function (lbl) {
                if (lbl.style.display === 'none') return;
                var inp = lbl.querySelector('input');
                if (inp.checked) {
                    var existing = participants.find(function (p) {
                        return p.type === lbl.dataset.type && String(p.id) === lbl.dataset.id;
                    });
                    checked.push({
                        type:  lbl.dataset.type,
                        id:    parseInt(lbl.dataset.id),
                        name:  lbl.dataset.name,
                        share: existing ? existing.share : 0,
                    });
                }
            });
        }
        if (checked.length !== participants.length) {
            var per = +(100 / (checked.length + 1)).toFixed(3);
            checked.forEach(function (p) { p.share = per; });
        }
        participants = checked;
    }

    // ── Sliders ────────────────────────────────────────────────────────────

    function rebuildSliders() {
        slidersEl.innerHTML = '';
        if (participants.length === 0) { slidersEl.style.display = 'none'; return; }
        slidersEl.style.display = 'block';

        var payerRow = document.createElement('div');
        payerRow.className = 'buddy-slider-row';
        payerRow.innerHTML =
            '<span class="buddy-slider-name" id="buddy-payer-label"></span>' +
            '<input type="range" id="buddy-payer-slider" min="0" max="100" step="0.1" value="0">' +
            '<span class="buddy-slider-pct" id="buddy-payer-pct"></span>' +
            '<span class="buddy-slider-amt secondary" id="buddy-payer-amt"></span>';
        slidersEl.appendChild(payerRow);
        updatePayerRow();

        document.getElementById('buddy-payer-slider').addEventListener('input', function () {
            var newShare = +parseFloat(this.value).toFixed(3);
            var delta    = newShare - implicitPayerShare();
            if (Math.abs(delta) < 0.001) return;
            var totalP = participants.reduce(function (a, p) { return a + p.share; }, 0);
            if (totalP > 0.001) {
                participants.forEach(function (p) {
                    p.share = Math.max(0, +(p.share - delta * (p.share / totalP)).toFixed(3));
                });
            } else {
                var perP = -delta / participants.length;
                participants.forEach(function (p) { p.share = Math.max(0, +(p.share + perP).toFixed(3)); });
            }
            clampSum();
            refreshSliderDisplays();
            this.value = implicitPayerShare();
            var pct = document.getElementById('buddy-payer-pct');
            if (pct) pct.textContent = implicitPayerShare().toFixed(1) + '%';
            var amt = document.getElementById('buddy-payer-amt');
            if (amt) amt.textContent = formatAmount(implicitPayerShare());
            serializeJSON();
        });

        participants.forEach(function (p, idx) {
            var row = document.createElement('div');
            row.className = 'buddy-slider-row';
            row.innerHTML =
                '<span class="buddy-slider-name">' + esc(p.name) + '</span>' +
                '<input type="range" id="bs-slider-' + idx + '" min="0" max="100" step="0.1" value="' + p.share + '">' +
                '<span class="buddy-slider-pct" id="bs-pct-' + idx + '">' + p.share.toFixed(1) + '%</span>' +
                '<span class="buddy-slider-amt secondary" id="bs-amt-' + idx + '">' + formatAmount(p.share) + '</span>';
            slidersEl.appendChild(row);
            row.querySelector('input').addEventListener('input', function () {
                var val   = +parseFloat(this.value).toFixed(3);
                var delta = val - participants[idx].share;
                participants[idx].share = val;
                var others = participants.filter(function (_, i) { return i !== idx; });
                if (others.length > 0) {
                    var perOther = delta / others.length;
                    others.forEach(function (o) {
                        o.share = Math.max(0, Math.min(100, +(o.share - perOther).toFixed(3)));
                    });
                }
                clampSum();
                refreshSliderDisplays();
                updatePayerRow();
                serializeJSON();
            });
        });
        serializeJSON();
    }

    function refreshSliderDisplays() {
        participants.forEach(function (p, idx) {
            var slider = document.getElementById('bs-slider-' + idx);
            var pct    = document.getElementById('bs-pct-' + idx);
            var amt    = document.getElementById('bs-amt-' + idx);
            if (slider) slider.value = p.share;
            if (pct)    pct.textContent = p.share.toFixed(1) + '%';
            if (amt)    amt.textContent = formatAmount(p.share);
        });
    }

    function updatePayerRow() {
        var share = implicitPayerShare();
        var lbl   = document.getElementById('buddy-payer-label');
        var pct   = document.getElementById('buddy-payer-pct');
        var amt   = document.getElementById('buddy-payer-amt');
        var slide = document.getElementById('buddy-payer-slider');
        if (lbl)   lbl.textContent = payerSel.options[payerSel.selectedIndex].text.split('(')[0].trim();
        if (pct)   pct.textContent = share.toFixed(1) + '%';
        if (amt)   amt.textContent = formatAmount(share);
        if (slide) slide.value = share;
    }

    function implicitPayerShare() {
        var sum = participants.reduce(function (a, p) { return a + p.share; }, 0);
        return Math.max(0, +(100 - sum).toFixed(3));
    }

    function clampSum() {
        var sum = participants.reduce(function (a, p) { return a + p.share; }, 0);
        if (sum > 100) {
            for (var i = participants.length - 1; i >= 0; i--) {
                var cut = Math.min(participants[i].share, sum - 100);
                participants[i].share = +(participants[i].share - cut).toFixed(3);
                sum = participants.reduce(function (a, p) { return a + p.share; }, 0);
                if (sum <= 100) break;
            }
        }
    }

    // ── Equal shares ───────────────────────────────────────────────────────

    equalBtn.addEventListener('click', function () {
        var per = +(100 / (participants.length + 1)).toFixed(3);
        participants.forEach(function (p) { p.share = per; });
        refreshSliderDisplays();
        updatePayerRow();
        serializeJSON();
    });

    // ── Serialize ──────────────────────────────────────────────────────────

    function serializeJSON() {
        jsonIn.value = JSON.stringify(participants.map(function (p) {
            return {type: p.type, id: p.id, share_percent: +p.share.toFixed(3)};
        }));
    }

    // ── Currency amount helpers ────────────────────────────────────────────
    // Parallel copy lives in initCardBuddy() in budget/templates/budget/express_creation.html.

    function getExpenseValue() {
        if (!valueInput) return 0;
        var v = parseFloat(String(valueInput.value).replace(',', '.'));
        return isNaN(v) || v <= 0 ? 0 : v;
    }

    function formatAmount(pct) {
        var val = getExpenseValue();
        if (val <= 0) return '';
        var amt = (pct / 100 * val).toFixed(2);
        return amt + ' ' + (cfg.currencySymbol || '');
    }

    // ── Escape helper ──────────────────────────────────────────────────────

    function esc(s) {
        return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ── Initialise from existing edit data ────────────────────────────────

    function initFromExisting() {
        // Set mode; fall back to group when no personal buddies exist
        var effectiveMode = (existingMode === 'single' && singleBuddies.length === 0 && groupsData.length > 0)
            ? 'group' : existingMode;
        if (effectiveMode === 'group' && modeRadioGroup) {
            modeRadioGroup.checked = true;
            currentMode = 'group';
            modeIn.value = 'group';
            if (groupSelectRow) groupSelectRow.style.display = 'block';
            if (groupSelectEl) {
                if (existingGroupId) groupSelectEl.value = String(existingGroupId);
                currentGroupId = parseInt(groupSelectEl.value) || null;
                groupIdIn.value = groupSelectEl.value;
            }
        } else {
            if (modeRadioSingle) modeRadioSingle.checked = true;
            currentMode = 'single';
            modeIn.value = 'single';
        }

        updateParticipantsLabel();
        buildPayerOptions();
        buildParticipantCheckboxes(false);

        // Restore payer selection
        var existingVal = existingUpfrontType + ':' + existingUpfrontId;
        if (Array.from(payerSel.options).some(function (o) { return o.value === existingVal; })) {
            payerSel.value = existingVal;
        }
        typeIn.value = payerSel.value.split(':')[0];
        idIn.value   = payerSel.value.split(':')[1];

        // Restore participant selection
        refreshParticipantCheckboxes();
        if (currentMode === 'single') {
            var sel = document.getElementById('buddy-participant-select');
            if (sel) {
                existingSpendings.forEach(function (sp) {
                    var candidate = sel.querySelector('option[data-type="' + sp.type + '"][data-id="' + sp.id + '"]');
                    if (candidate) sel.value = candidate.value;
                });
            }
        } else {
            existingSpendings.forEach(function (sp) {
                participantsEl.querySelectorAll('.buddy-participant-cb').forEach(function (lbl) {
                    if (lbl.dataset.type === sp.type && parseInt(lbl.dataset.id) === sp.id) {
                        lbl.querySelector('input').checked = true;
                    }
                });
            });
        }
        syncParticipantsFromCheckboxes();

        // Apply saved share percentages
        existingSpendings.forEach(function (sp) {
            var p = participants.find(function (x) { return x.type === sp.type && x.id === sp.id; });
            if (p) p.share = sp.share_percent;
        });

        updatePayerNotice();
        rebuildSliders();
        refreshSliderDisplays();
        updatePayerRow();
        serializeJSON();
    }
})();
