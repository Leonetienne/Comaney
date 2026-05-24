import dateRange from './date-range.js';
import { EXP_PAGE_SIZE } from './pagination-config.js';
window._dateRange = dateRange;
window._expPageSize = EXP_PAGE_SIZE;

window._attachPaginator = function(root, selector, pageSize) {
    pageSize = pageSize || window._expPageSize || 100;
    var currentPage = 1;
    var topNav = null;
    var botNav = null;

    function getItems() { return Array.from(root.querySelectorAll(selector)); }

    function buildNav(total, totalPages, scrollOnClick) {
        var nav = document.createElement('nav');
        nav.className = 'exp-pagination' + (scrollOnClick ? '' : ' exp-pagination--top');
        nav.setAttribute('aria-label', 'Pages');

        function makeBtn(label, targetPage, isActive, isDisabled) {
            var b = document.createElement('button');
            b.type = 'button';
            b.textContent = label;
            b.className = 'btn btn-sm ' + (isActive ? 'btn-primary' : 'btn-secondary');
            if (isDisabled) {
                b.disabled = true;
            } else {
                b.addEventListener('click', function() {
                    currentPage = targetPage;
                    render();
                    if (scrollOnClick) root.scrollIntoView({ behavior: 'smooth', block: 'start' });
                });
            }
            return b;
        }

        nav.appendChild(makeBtn('|<', 1, false, currentPage === 1));
        nav.appendChild(makeBtn('<', currentPage - 1, false, currentPage === 1));

        var count = Math.min(7, totalPages);
        var lo = currentPage - Math.floor(count / 2);
        if (lo < 1) lo = 1;
        if (lo + count - 1 > totalPages) lo = totalPages - count + 1;
        var hi = lo + count - 1;
        for (var p = lo; p <= hi; p++) {
            nav.appendChild(makeBtn(String(p), p, p === currentPage, false));
        }

        nav.appendChild(makeBtn('>', currentPage + 1, false, currentPage === totalPages));
        nav.appendChild(makeBtn('>|', totalPages, false, currentPage === totalPages));

        var info = document.createElement('span');
        info.className = 'exp-pagination__info';
        info.textContent = 'Page ' + currentPage + ' of ' + totalPages + ' (' + total + ' entries)';
        nav.appendChild(info);

        return nav;
    }

    function render() {
        var all = getItems();
        var total = all.length;
        var totalPages = Math.max(1, Math.ceil(total / pageSize));
        if (currentPage > totalPages) currentPage = totalPages;
        if (currentPage < 1) currentPage = 1;

        var start = (currentPage - 1) * pageSize;
        var end = start + pageSize;
        all.forEach(function(el, i) {
            el.style.display = (i >= start && i < end) ? '' : 'none';
        });

        if (topNav) { topNav.remove(); topNav = null; }
        if (botNav) { botNav.remove(); botNav = null; }
        if (totalPages <= 1) return;

        topNav = buildNav(total, totalPages, false);
        botNav = buildNav(total, totalPages, true);

        root.parentNode.insertBefore(topNav, root);
        root.appendChild(botNav);
    }

    render();

    // If the URL has ?scroll_to=<uid>, jump to the right page and scroll there.
    // Works for both paginated (approved) and non-paginated (pending) items.
    (function() {
        var scrollTo = new URLSearchParams(window.location.search).get('scroll_to');
        if (!scrollTo) return;
        var params = new URLSearchParams(window.location.search);
        params.delete('scroll_to');
        var clean = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        history.replaceState(null, '', clean);
        var target = document.getElementById('expense-' + scrollTo)
                  || document.getElementById('pending-' + scrollTo);
        if (!target) return;
        if (root.contains(target)) {
            var idx = getItems().indexOf(target);
            if (idx !== -1) {
                var targetPage = Math.floor(idx / pageSize) + 1;
                if (targetPage !== currentPage) { currentPage = targetPage; render(); }
            }
        }
        setTimeout(function() {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    })();

    return { reset: function() { currentPage = 1; render(); } };
};
