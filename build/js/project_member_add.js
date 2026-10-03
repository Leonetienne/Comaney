// Project Settings tab, "Add members" (buddies/templates/buddies/project_settings.html).
//
// Invite by email: a combobox suggesting the admin's direct buddies (matched
// case-insensitively on first name, last name or email) plus a hint below the
// input saying whether the typed email belongs to a direct buddy.
// Add offline member: warns when the typed name looks like an email address
// or matches a direct buddy (one warning at most), and asks for confirmation
// before creating the offline record anyway.
//
// The contact list is rendered server-side as hidden <li> elements (so the
// avatar markup is the shared partials/_avatar.html), this file only filters
// and reads them. Both hint paragraphs always occupy their line (see
// .input-hint), so setting or clearing a hint never shifts the layout.

const MAX_SUGGESTIONS = 8;

function contactFromItem(li) {
    const first = li.dataset.firstName || '';
    const last = li.dataset.lastName || '';
    return {
        li,
        email: li.dataset.email || '',
        first,
        last,
        fullName: `${first} ${last}`.trim(),
        isMember: li.dataset.member === '1',
    };
}

// The one place deciding whether a typed text refers to a direct buddy:
// case-insensitive substring of their first name, last name or email. Used by
// both the invite suggestions and the offline-member name warning.
function matchingContacts(contacts, query, {excludeMembers = false} = {}) {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    return contacts.filter((c) => !(excludeMembers && c.isMember) && (
        c.first.toLowerCase().includes(q)
        || c.last.toLowerCase().includes(q)
        || c.email.toLowerCase().includes(q)
    ));
}

function setHint(el, text, kind) {
    el.textContent = text;
    el.classList.toggle('input-hint--success', kind === 'success');
    el.classList.toggle('input-hint--warning', kind === 'warning');
}

function setupInviteCombobox(contacts) {
    const input = document.getElementById('project-invite-email');
    const list = document.getElementById('project-invite-suggestions');
    const check = document.getElementById('project-invite-check');
    const hint = document.getElementById('project-invite-hint');
    if (!input || !list || !hint) return;

    let visible = [];
    let active = -1;

    function setActive(idx) {
        visible.forEach((c, i) => c.li.classList.toggle('is-active', i === idx));
        active = idx;
        if (idx >= 0) visible[idx].li.scrollIntoView({block: 'nearest'});
    }

    function close() {
        list.hidden = true;
        input.setAttribute('aria-expanded', 'false');
        setActive(-1);
    }

    function filter() {
        const q = input.value.trim().toLowerCase();
        // Existing members stay out of the suggestions: inviting them again
        // would only say "already a member".
        visible = matchingContacts(contacts, q, {excludeMembers: true}).slice(0, MAX_SUGGESTIONS);
        contacts.forEach((c) => { c.li.hidden = !visible.includes(c); });
        // An exact email match is already chosen; nothing left to suggest.
        if (visible.length === 1 && visible[0].email.toLowerCase() === q) visible = [];
        list.hidden = visible.length === 0;
        input.setAttribute('aria-expanded', visible.length ? 'true' : 'false');
        setActive(-1);
    }

    function updateHint() {
        const email = input.value.trim().toLowerCase();
        const isContact = email && contacts.some((c) => c.email.toLowerCase() === email);
        check.classList.toggle('is-visible', Boolean(isContact));
        if (isContact) {
            setHint(hint, 'This buddy is in your contacts', 'success');
        } else if (email.includes('@')) {
            // Only judge something that is shaped like an email address, not a
            // half-typed name the suggestions above are still matching.
            setHint(hint, 'This buddy is not in your contact list', null);
        } else {
            setHint(hint, '', null);
        }
    }

    function choose(contact) {
        input.value = contact.email;
        close();
        updateHint();
        input.focus();
    }

    input.addEventListener('input', () => { filter(); updateHint(); });
    input.addEventListener('focus', filter);
    input.addEventListener('blur', () => setTimeout(close, 150));
    input.addEventListener('keydown', (e) => {
        if (list.hidden) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((active + 1) % visible.length);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive(active <= 0 ? visible.length - 1 : active - 1);
        } else if (e.key === 'Enter' && active >= 0) {
            e.preventDefault();
            choose(visible[active]);
        } else if (e.key === 'Escape') {
            close();
        }
    });
    contacts.forEach((c) => {
        // Keep focus in the input so its blur doesn't close the list before
        // the click lands; select on click itself, which also covers clicks
        // that come without a mousedown (assistive tech, scripted clicks).
        c.li.addEventListener('mousedown', (e) => e.preventDefault());
        c.li.addEventListener('click', () => choose(c));
    });
}

// Deliberately loose: anything shaped like "x@y.z" is treated as an email.
const EMAIL_LIKE = /^\S+@\S+\.\S+$/;

function setupOfflineNameCheck(contacts) {
    const form = document.getElementById('project-add-dummy-form');
    const input = document.getElementById('project-add-dummy-name');
    const hint = document.getElementById('project-add-dummy-hint');
    if (!form || !input || !hint) return;

    // The single warning for the current name, or null. Checks are ordered and
    // only the first that applies is reported, so the hint and the submit
    // dialog can never show two warnings at once. An email address comes
    // first: it means the user expects an invitation, which this form never
    // sends (it also covers a buddy's own email, which would match below).
    function currentWarning() {
        const name = input.value.trim();
        if (EMAIL_LIKE.test(name)) {
            return 'This looks like an email address. Offline members are only placeholders: '
                + 'nobody gets invited or emailed. To invite someone, use "Invite by email" above.';
        }
        const contact = matchingContacts(contacts, name)[0];
        if (contact) {
            return `You already have a contact named ${contact.fullName}. `
                + 'You might want to invite their user instead of creating an offline record.';
        }
        return null;
    }

    input.addEventListener('input', () => {
        const warning = currentWarning();
        setHint(hint, warning || '', warning ? 'warning' : null);
    });

    form.addEventListener('submit', (e) => {
        const warning = currentWarning();
        if (!warning) return;
        e.preventDefault();
        window.confirmDialog(warning + ' Add the offline member anyway?', 'Add')
            .then(() => form.submit())
            .catch(() => {});
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const contacts = Array.from(document.querySelectorAll('#project-invite-suggestions .contact-suggestion'))
        .map(contactFromItem);
    setupInviteCombobox(contacts);
    setupOfflineNameCheck(contacts);
});
