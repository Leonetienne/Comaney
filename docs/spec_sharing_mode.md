# Spec: Dashboard Sharing Mode Toggle

## Übersicht

Ein konditioneller Toggle im Dashboard, der zwischen zwei Berechnungsmodi umschaltet:

- **Persönlich**: nur eigene Expenses (voller Betrag, Participant-Shares ignoriert)
- **Geteilt**: eigene und fremde Expenses anteilig nach Participant-Share

---

## Aktivierungsbedingung

Der Toggle wird nur eingeblendet, wenn der Nutzer mindestens eine der folgenden Bedingungen erfüllt:

- Hat mindestens einen bestätigten Buddy (`BuddyLink` mit `user_a=feuser` oder `user_b=feuser`)
- Ist Mitglied in mindestens einem Nicht-Solo-Projekt (`ProjectMember.feuser=feuser` in einem Projekt, das `is_solo=False` ergibt, d.h. mehr als 1 FeUser-Mitglied oder mindestens 1 DummyUser-Mitglied)

Ist die Bedingung nicht erfüllt, wird der Toggle komplett ausgeblendet; der Dashboard-Code bleibt unverändert (immer Persönlich-Modus).

---

## Modi im Detail

### Persönlich (Standard, bisheriges Verhalten)

- Queryset: `owning_feuser=feuser`
- `value` wird 1:1 verwendet; `BuddySpending`-Einträge werden vollständig ignoriert
- Settlement-Expenses: wie bisher (YAML-Filter oder eigene Logik der Card entscheidet)
- Kern-Frage: "Was habe ich von meinem Konto ausgegeben?"

### Geteilt (Buddy-Modus)

- Queryset: `owning_feuser=feuser` **ODER** `buddy_spendings__participant_feuser=feuser`
  - `is_buddies_settlement=True` immer ausfiltern
  - `.distinct()` wegen JOIN-Duplikaten
- Jede Expense erhält eine annotierte `effective_value`-Spalte (Regeln s.u.)
- Alle Card-Berechnungen (`_compute_cell`, `_compute_chart`, `_compute_list`, `_compute_line_chart`) verwenden `effective_value` statt `value`
- Kern-Frage: "Zu welchen Zahlungen habe ich mich verpflichtet?"

#### Berechnungsregeln für `effective_value`

| Situation | effective_value |
|---|---|
| `owning_feuser=feuser`, keine `BuddySpending`-Zeilen für diese Expense | `value` (voller Betrag) |
| `owning_feuser=feuser`, `BuddySpending`-Zeilen vorhanden, aber keiner für `feuser` | `0` |
| `owning_feuser=feuser`, eigener `BuddySpending`-Eintrag vorhanden* | `value * share_percent / 100` |
| `owning_feuser != feuser`, `participant_feuser=feuser` in `BuddySpending` | `value * share_percent / 100` |

*Laut Datenmodell ist der Expense-Owner niemals in `BuddySpending` eingetragen (`"The expense owner is never a participant here"`). Daher ist Zeile 3 aktuell nicht erreichbar, wird aber defensiv abgedeckt.

#### DB-Implementierung (Subqueries + Case/When)

```python
from django.db.models import Subquery, OuterRef, Exists, Case, When, Value, F, ExpressionWrapper, DecimalField

my_share_subq = Subquery(
    BuddySpending.objects.filter(
        expense=OuterRef('pk'),
        participant_feuser=feuser,
    ).values('share_percent')[:1]
)
has_any_spendings_subq = Exists(
    BuddySpending.objects.filter(expense=OuterRef('pk'))
)

qs = (
    Expense.objects
    .filter(
        Q(owning_feuser=feuser) | Q(buddy_spendings__participant_feuser=feuser),
        date_due__gte=start,
        date_due__lte=end,
        deactivated=False,
        is_dummy=False,
        is_buddies_settlement=False,
    )
    .distinct()
    .annotate(_my_share=my_share_subq, _has_any=has_any_spendings_subq)
    .annotate(
        effective_value=Case(
            # Eigene Expense, keine BuddySpending: voller Betrag
            When(owning_feuser=feuser, _has_any=False,      then=F('value')),
            # Eigene Expense, BuddySpending aber nicht für mich: 0
            When(owning_feuser=feuser, _my_share__isnull=True,
                 then=Value(Decimal('0'), output_field=DecimalField())),
            # Eigene Expense, eigener BuddySpending-Eintrag: anteilig (defensiv)
            When(owning_feuser=feuser, _my_share__isnull=False,
                 then=ExpressionWrapper(
                     F('value') * F('_my_share') / Value(100),
                     output_field=DecimalField())),
            # Fremde Expense, ich bin Participant: anteilig
            default=ExpressionWrapper(
                F('value') * F('_my_share') / Value(100),
                output_field=DecimalField()),
            output_field=DecimalField(),
        )
    )
)
```

---

## Persistenz

Gleicher Mechanismus wie der Monat/Jahr-Toggle: **URL-Parameter**.

- Persönlich (Standard): kein extra Parameter (oder `?sharing=personal`)
- Geteilt: `?sharing=shared`

Der Parameter wird durch alle Navigationslinks im `_month_nav.html` durchgeschleift (analog zu `view=year` heute).

---

## Änderungen je Schicht

### Backend: `budget/views/dashboard.py`

- `dashboard()`-View: Bedingung prüfen (`has_buddy_or_multiuser_project(feuser)`), `nav_show_sharing_toggle` und `nav_sharing_mode` an Template-Context übergeben

### Backend: `budget/views/dashboard_cards_api.py`

- `_period_qs()`: liest `request.GET.get('sharing')`. Bei `'shared'` baut es das Buddy-Queryset (s.o.) und gibt zusätzlich `sharing_mode='shared'` im `period_info`-Dict zurück.
- `_card_to_json()`: leitet `sharing_mode` an `compute_card_data()` weiter.

### Backend: `budget/dashboard_cards.py`

- `compute_card_data()` und alle `_compute_*`-Funktionen: neuer optionaler Parameter `value_field: str = 'value'`. Im Geteilt-Modus wird `'effective_value'` übergeben.
- Überall `Sum('value')` → `Sum(value_field)`, `F('value')` → `F(value_field)`.
- `method=custom` / `python=...` Cards: nutzen interne `query_sum()`-Hilfsfunktion, die ebenfalls `value_field` respektieren muss.

### Backend: Hilfsfunktion

Neue Funktion `has_buddy_or_multiuser_project(feuser) -> bool` in einem geeigneten Modul (z.B. `buddies/services/` oder inline in der View):

```python
def has_buddy_or_multiuser_project(feuser) -> bool:
    from buddies.models import BuddyLink, ProjectMember
    has_buddy = BuddyLink.for_user(feuser).exists()
    if has_buddy:
        return True
    # Nicht-Solo-Projekt: mind. 1 weiterer FeUser oder mind. 1 Dummy im Projekt
    return ProjectMember.objects.filter(
        feuser=feuser,
        group__members__feuser__isnull=False,  # mind. ein FeUser-Mitglied...
    ).exclude(
        group__members__feuser=feuser,  # ...der nicht ich selbst bin
    ).exists() or ProjectMember.objects.filter(
        feuser=feuser,
        group__members__dummy__isnull=False,
    ).exists()
```

*(Exakte Implementierung kann vereinfacht werden; Semantik: Project.is_solo=False für irgendein Projekt, in dem feuser Mitglied ist.)*

### Frontend: `templates/partials/_month_nav.html`

- Neuer Block: `.sharing-toggle`, rechts neben den bestehenden Controls, aber nur wenn `nav_show_sharing_toggle`
- Gleicher `period-toggle`-CSS-Stil wie der Monate/Jahre-Toggle
- Links müssen den bestehenden `year`/`month`/`view`-Parameter beibehalten und `sharing` hinzufügen/entfernen

```html
{% if nav_show_sharing_toggle %}
<div class="period-toggle">
  <a href="?year={{ nav_year }}{% if nav_mode == 'month' %}&month={{ nav_month }}{% else %}&view=year{% endif %}"
     class="period-toggle__opt{% if nav_sharing_mode != 'shared' %} active{% endif %}">
     Persönlich
  </a>
  <a href="?year={{ nav_year }}{% if nav_mode == 'month' %}&month={{ nav_month }}{% else %}&view=year{% endif %}&sharing=shared"
     class="period-toggle__opt{% if nav_sharing_mode == 'shared' %} active{% endif %}">
     Geteilt
  </a>
</div>
{% endif %}
```

### Frontend: `budget/templates/budget/dashboard.html`

- `window.DASHBOARD_CONFIG` erhält `sharingMode: "{{ nav_sharing_mode|default:'' }}"`.

### Frontend: `build/js/dashboard.js`

- `dashboardBoard` State: `sharingMode: ''`
- `init()`: liest `cfg.sharingMode`
- `_periodParams`: hängt `&sharing=shared` an, wenn `this.sharingMode === 'shared'`

### SCSS: `build/scss/_month-nav.scss`

- Nur Layout: `.month-nav` erhält `flex-wrap: wrap` für sehr schmale Screens; keine neuen Styles notwendig (`.period-toggle` wird 1:1 wiederverwendet).

---

## Views/Templates, die `_month_nav.html` einbinden

`_month_nav.html` wird auch in `expenses_list.html` eingebunden. Der Toggle darf dort **nicht** erscheinen (macht für die Expense-Liste keinen Sinn). Lösung: Der Template-Context für die Expense-List-View setzt `nav_show_sharing_toggle=False` explizit, oder der View gibt die Variable gar nicht mit.

---

## Tests

### Unit-Tests (`tests/unit/`)

- `test_period_qs_personal_mode`: `_period_qs` ohne `sharing`-Parameter liefert nur `owning_feuser=feuser`, kein `effective_value`-Annotation.
- `test_period_qs_shared_mode_own_expense_no_spendings`: eigene Expense ohne BuddySpending → `effective_value = value`.
- `test_period_qs_shared_mode_own_expense_spendings_without_me`: eigene Expense mit BuddySpending, aber nicht für mich → `effective_value = 0`.
- `test_period_qs_shared_mode_foreign_expense_as_participant`: fremde Expense mit `participant_feuser=me, share_percent=30` → `effective_value = value * 0.30`.
- `test_period_qs_shared_mode_settlement_excluded`: `is_buddies_settlement=True`-Expense erscheint im Geteilt-Modus nicht.
- `test_has_buddy_or_multiuser_project_buddy`: User mit BuddyLink → True.
- `test_has_buddy_or_multiuser_project_solo_project`: User nur in Solo-Projekt → False.
- `test_has_buddy_or_multiuser_project_multi_user_project`: User in Projekt mit 2 FeUsern → True.
- `test_compute_cell_uses_effective_value`: `_compute_cell` summiert `effective_value` wenn `value_field='effective_value'`.

### E2E-Tests

- Toggle erscheint nur wenn Bedingung erfüllt; testen mit/ohne BuddyLink.
- Klick auf "Geteilt": URL enthält `sharing=shared`, Cards werden neu geladen.
- Wert einer Cell-Card im Geteilt-Modus entspricht dem anteiligen Betrag.

---

## Query-Language-Erweiterungen

Alle Änderungen in `budget/query_parser.py`. Die Funktion `apply_query(qs, query_str)` wird zu `apply_query(qs, query_str, feuser=None)` erweitert; `feuser` wird für `me`-Keywords und Overlay-Lookups benötigt. Alle Aufrufer, die den aktuellen User kennen, übergeben ihn.

### Überblick der Änderungen

| Filter | Vorher | Nachher |
|---|---|---|
| `buddy=` | bool + Name-Search | **entfernt**, ersetzt durch `shared=` und `participant=` |
| `shared=` | — | neu: bool, ob Expense BuddySpending-Zeilen hat |
| `participant=` | — | neu: Person ist Owner oder Participant |
| `payer=` | — | neu: Payer-Matching (Owner, Dummy-Upfront-Payer, Participant-Dummy) |
| `project=` | `none` + Name | bool (true/false) + Name (bestehend: `none` = falsisch) |
| `payee=` | nur Substring | `none` für "kein Payee" ergänzt |
| `tag=` | nur Expense.tags | + Overlay-Tags des feuser |
| `cat=` | nur Expense.category | + Overlay-Kategorie des feuser |
| Freitext/note | Expense.note | + Overlay-Note des feuser (nur wenn non-null) |

---

### `shared=<bool>`

Ersetzt `buddy=<bool>`. Matched Expenses mit (`true`) oder ohne (`false`) BuddySpending-Einträge.

```python
# shared=true/yes/1
Q(pk__in=Expense.objects.filter(buddy_spendings__isnull=False).values('pk'))

# shared=false/no/0
Q(buddy_spendings__isnull=True)
```

Akzeptierte Werte: `true`, `yes`, `1` (truthy) / `false`, `no`, `0` (falsy).

---

### `participant=<me|name|email>`

Neu. Matched Expenses, bei denen die gesuchte Person **entweder Owner oder BuddySpending-Participant** ist.

- `me` (erfordert `feuser`):
  ```python
  Q(pk__in=Expense.objects.filter(
      Q(owning_feuser=feuser) | Q(buddy_spendings__participant_feuser=feuser)
  ).values('pk'))
  ```
- Name/E-Mail (substring):
  ```python
  Q(pk__in=Expense.objects.filter(
      Q(owning_feuser__first_name__icontains=val)
      | Q(owning_feuser__last_name__icontains=val)
      | Q(owning_feuser__email__icontains=val)
      | Q(buddy_spendings__participant_feuser__first_name__icontains=val)
      | Q(buddy_spendings__participant_feuser__last_name__icontains=val)
      | Q(buddy_spendings__participant_feuser__email__icontains=val)
      | Q(buddy_spendings__participant_dummy__display_name__icontains=val)
  ).values('pk'))
  ```

Hinweis: `pk__in`-Subquery ist zwingend, um JOIN-Duplikate bei mehreren Participants zu vermeiden.

---

### `payer=<me|name|email>`

Neu. Matched nur nach `owning_feuser`.

- `me` (erfordert `feuser`): `Q(owning_feuser=feuser)`
- Name/E-Mail (substring):
  ```python
  Q(owning_feuser__first_name__icontains=val)
  | Q(owning_feuser__last_name__icontains=val)
  | Q(owning_feuser__email__icontains=val)
  ```

---

### `project=<bool|name>`

Bestehendes `project=none` (kein Projekt) bleibt. Ergänzung:

- `true/yes/1` → `Q(project__isnull=False)` (hat irgendein Projekt)
- `false/no/0` und `none` → `Q(project__isnull=True)` (kein Projekt)
- Alles andere → `Q(project__name__icontains=val)` (wie bisher)

```python
def _project_q(val: str) -> Q:
    if val in ('false', 'no', '0', 'none'):
        return Q(project__isnull=True)
    if val in ('true', 'yes', '1'):
        return Q(project__isnull=False)
    return Q(project__name__icontains=val)
```

---

### `payee=none`

Erweiterung des bestehenden `payee=`-Filters. `none` matched Expenses ohne Payee (leerer String oder NULL):

```python
def _payee_q(val: str) -> Q:
    if val == 'none':
        return Q(payee='') | Q(payee__isnull=True)
    return Q(payee__icontains=val)
```

---

### `tag=<name>` mit Overlay-Unterstützung

Derzeit: nur `Expense.tags`. Neu: auch `ExpenseDataOverlay.tags` für den aktuellen feuser.

- `tag=none`: Expense hat keine direkten Tags UND kein Overlay mit Tags für feuser
  ```python
  Q(tags__isnull=True) & (
      Q(data_overlays__feuser=feuser, data_overlays__tags__isnull=False)
      .using_pk_in_workaround()  # s.u.
  )
  # Genauer: Expense hat keine Tags UND kein Overlay des feuser mit Tags
  ~Q(pk__in=Expense.objects.filter(tags__isnull=False).values('pk'))
  & ~Q(pk__in=Expense.objects.filter(
        data_overlays__feuser=feuser,
        data_overlays__tags__isnull=False
      ).values('pk'))
  ```
- `tag=<name>`: Expense.tags ODER Overlay-Tags des feuser
  ```python
  Q(pk__in=Expense.objects.filter(tags__title__icontains=val).values('pk'))
  | Q(pk__in=Expense.objects.filter(
        data_overlays__feuser=feuser,
        data_overlays__tags__title__icontains=val
      ).values('pk'))
  ```

Wenn `feuser=None`: Overlay-Anteil wird weggelassen (Fallback auf bisheriges Verhalten).

---

### `cat=<name>` mit Overlay-Unterstützung

Analog zu `tag=`.

- `cat=none`:
  ```python
  ~Q(pk__in=Expense.objects.filter(category__isnull=False).values('pk'))
  & ~Q(pk__in=Expense.objects.filter(
        data_overlays__feuser=feuser,
        data_overlays__category__isnull=False
      ).values('pk'))
  ```
- `cat=<name>`:
  ```python
  Q(category__title__icontains=val)
  | Q(pk__in=Expense.objects.filter(
        data_overlays__feuser=feuser,
        data_overlays__category__title__icontains=val
      ).values('pk'))
  ```

Wenn `feuser=None`: nur `Expense.category` (wie bisher).

---

### Freitext / Note mit Overlay-Unterstützung

`_term_q` matcht derzeit `title`, `payee`, `note` und Buddy-Namen. Note-Suche wird um Overlay-Notes erweitert.

```python
def _term_q(val: str, model=None, feuser=None) -> Q:
    q = Q(title__icontains=val) | Q(payee__icontains=val) | Q(note__icontains=val)
    if feuser is not None:
        # Overlay-Note nur wenn non-null (null = "Expense-Note erben")
        q |= Q(pk__in=model.objects.filter(
            data_overlays__feuser=feuser,
            data_overlays__note__icontains=val,
            data_overlays__note__isnull=False,
        ).values('pk')) if model else Q(
            data_overlays__feuser=feuser,
            data_overlays__note__icontains=val,
            data_overlays__note__isnull=False,
        )
    if model is not None:
        q |= Q(pk__in=model.objects.filter(_buddy_name_q(val)).values('pk'))
    return q
```

---

### API-Änderung: `apply_query` Signatur

```python
def apply_query(qs, query_str: str, feuser=None):
    ...
    return qs.filter(_compile(_tokenize(s.lower()), qs.model, feuser=feuser)).distinct()
```

`_compile` und `make_filter` erhalten ebenfalls `feuser=None`. Alle bisherigen Aufrufer ohne `feuser` sind weiterhin kompatibel (Overlay-Features werden dann übersprungen).

Stellen, die `feuser` übergeben sollen:
- `budget/views/dashboard_cards_api.py` → `compute_card_data()` → `_filtered_qs()` → `apply_query()`
- `budget/views/expenses.py` (Expenses-List-Suche)

---

### Tests für Query-Language-Erweiterungen

Alle als Unit-Tests in `tests/unit/test_query_parser.py`:

- `test_shared_true`: Expense mit BuddySpending wird gematcht, ohne nicht.
- `test_shared_false`: Inverse.
- `test_participant_me`: Expense als Owner und als Participant wird gematcht; fremde Expense ohne Bezug nicht.
- `test_participant_name`: Substring-Match auf Owner und Participants.
- `test_owner_me`: nur eigene Expenses.
- `test_owner_name`: Substring auf Owner-Name.
- `test_project_bool_true`: Expenses mit Projekt.
- `test_project_bool_false`: Expenses ohne Projekt.
- `test_project_none_alias`: `project=none` weiterhin kompatibel.
- `test_payee_none`: Expenses ohne Payee.
- `test_tag_overlay`: `tag=<name>` matched Expense mit passendem Overlay-Tag.
- `test_tag_none_with_overlay`: `tag=none` schließt Expense mit Overlay-Tag aus.
- `test_cat_overlay`: `cat=<name>` matched Expense mit passender Overlay-Kategorie.
- `test_note_overlay`: Freitext-Suche matched Overlay-Note.
- `test_note_overlay_null_skipped`: Overlay mit `note=None` wird nicht gematcht.
- `test_buddy_filter_removed`: `buddy=` wird als unbekannter Filter zu Freitext (kein Crash).

---

## Nicht im Scope

- Die REST-API unter `api/views/dashboard.py` (Bearer-Auth) bleibt unverändert.
- Custom-`python`-Cards (`method=custom`) im Geteilt-Modus: verhalten sich korrekt nur wenn sie interne `query_sum()`-Hilfsfunktionen nutzen; direkte DB-Queries im Python-Block können den `value_field` nicht respektieren (dokumentiertes Limitation).
- Kein neues Datenbankfeld, keine Migration nötig.
