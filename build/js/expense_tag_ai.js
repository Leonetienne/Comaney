// "AI: select tags" button for the expense and recurring-expense create+edit
// forms (expense_form.html / scheduled_form.html). Reuses the same
// underlying AI logic as the Unclassified Expenses page's per-row "Let AI
// solve" (budget.unclassified_ai.suggest_tags via expense_ai_suggest_tags),
// just fed the form's current, possibly-unsaved field values instead of a
// DB expense/overlay.
(function () {
    var btn = document.getElementById('tag-ai-btn');
    if (!btn) return;

    var form = btn.closest('form');
    if (!form) return;

    var tagsWrap  = form.querySelector('.tag-cb-wrap');
    var titleIn   = document.getElementById('id_title');
    var payeeIn   = document.getElementById('id_payee');
    var typeIn    = document.getElementById('id_type');
    var valueIn   = document.getElementById('id_value');
    var noteIn    = document.getElementById('id_note');
    var categoryIn = document.getElementById('id_category');
    var dateIn    = document.getElementById('id_date_due') || document.getElementById('id_repeat_base_date');
    var csrfIn    = form.querySelector('[name=csrfmiddlewaretoken]');
    var costEl    = document.getElementById('tag-ai-cost');
    var errEl     = document.getElementById('tag-ai-error');
    var labelEl   = btn.querySelector('.ai-btn-label');

    btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var originalLabel = labelEl ? labelEl.textContent : '';
        btn.disabled = true;
        if (labelEl) labelEl.textContent = 'Thinking…';
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
        if (costEl) { costEl.style.display = 'none'; }

        fetch(btn.dataset.url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfIn ? csrfIn.value : '',
            },
            body: JSON.stringify({
                title: titleIn ? titleIn.value : '',
                payee: payeeIn ? payeeIn.value : '',
                type: typeIn ? typeIn.value : '',
                value: valueIn ? valueIn.value : '',
                note: noteIn ? noteIn.value : '',
                category_uid: categoryIn ? categoryIn.value : '',
                date_due: dateIn ? dateIn.value : '',
            }),
        })
            .then(function (res) {
                return res.json().catch(function () { return {}; }).then(function (data) {
                    return { ok: res.ok, status: res.status, data: data };
                });
            })
            .then(function (r) {
                if (!r.ok) {
                    if (r.status === 402) btn.style.display = 'none';
                    if (errEl) {
                        errEl.textContent = r.data.error || 'AI suggestion failed. Please try again.';
                        errEl.style.display = '';
                    }
                    return;
                }
                if (tagsWrap) {
                    var wanted = {};
                    (r.data.tag_uids || []).forEach(function (uid) { wanted[String(uid)] = true; });
                    tagsWrap.querySelectorAll('input[type=checkbox]').forEach(function (cb) {
                        cb.checked = !!wanted[cb.value];
                    });
                }
                if (costEl) {
                    var cost = typeof r.data.cost_cents === 'number' ? r.data.cost_cents : 0;
                    costEl.textContent = 'AI cost: ' + cost.toFixed(1) + ' ¢';
                    costEl.style.display = '';
                }
            })
            .catch(function () {
                if (errEl) {
                    errEl.textContent = 'AI suggestion failed. Please try again.';
                    errEl.style.display = '';
                }
            })
            .finally(function () {
                btn.disabled = false;
                if (labelEl) labelEl.textContent = originalLabel;
            });
    });
})();
