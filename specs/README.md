# Comaney Requirements Database

This directory is the single source of requirements for Comaney. Requirements are
written first: a change in behaviour starts here, and the code is then built to
satisfy it. An item without a `Status:` line holds for the current code; an item
marked `Status: proposed` is agreed but not implemented yet.

## Format

Three established standards, each doing one job:

| Concern | Standard | What it gives us |
|---|---|---|
| Document structure and attributes | ISO/IEC/IEEE 29148:2018 (SRS) | Introduction, glossary, features, functional requirements, quality requirements, design constraints |
| Requirement wording | EARS (Easy Approach to Requirements Syntax, Mavin et al.) | Five sentence templates that keep every statement testable |
| Markdown item syntax | OpenFastTrack (OFT) | Stable IDs, versioning, `Covers` links, machine-checkable with `oft trace` |

### EARS templates

| Pattern | Template |
|---|---|
| Ubiquitous | The system shall *response*. |
| Event-driven | **When** *trigger*, the system shall *response*. |
| State-driven | **While** *state*, the system shall *response*. |
| Unwanted behaviour | **If** *unwanted condition*, **then** the system shall *response*. |
| Optional feature | **Where** *feature is configured*, the system shall *response*. |

Patterns may be combined ("While ..., when ..., the system shall ...").
"Shall" marks a binding requirement. "Should" is not used: every item is binding,
proposed ones included.

### Item syntax (OpenFastTrack)

```markdown
### Login rate limit
`req~example.login-rate-limit~1`

If 5 failed login attempts ..., then the system shall ...

Rationale:
Why this exists, when it is not obvious.

Comment:
Optional notes, e.g. known edge cases.

Covers:
- `feat~accounts~1`

Tags: Security

Status: proposed
```

- **ID**: `<type>~<name>~<revision>`. Types: `feat` (system feature, in
  [features.md](features.md)) and `req` (requirement, in `requirements/`).
  Names are dot-separated, lower case, each segment starting with a letter.
- **Revision**: bump it whenever the meaning of a requirement changes. Never reuse
  an ID for a different requirement; delete obsolete items instead.
- **Covers**: every `req` covers exactly one `feat`. Every `feat` declares
  `Needs: req`, so a tracing run reports any feature without requirements.
- **Tags** (optional): `Security`, `Privacy`, `Demo` (demo-account restriction),
  `UI`, `Performance`, `Operations`. Used for filtering.
- **Rationale** only where the reason is not evident from the statement.
- **Status** (OFT field): `proposed` while the code does not satisfy the item yet.
  The change that implements it deletes the line. No other status values are used.

### Tracing

With [OpenFastTrack](https://github.com/itsallcode/openfasttrack) installed:

```bash
oft trace specs/features.md specs/requirements/
```

It checks that IDs are unique, every `Covers` target exists and every feature is
covered by at least one requirement.

## Layout

| File | Content |
|---|---|
| [introduction.md](introduction.md) | Purpose, scope, product overview, user classes, out-of-scope list |
| [glossary.md](glossary.md) | Domain terms |
| [features.md](features.md) | System feature list (`feat` items) |
| [requirements/](requirements/) | Functional requirements, one file per feature area |
| [requirements/quality.md](requirements/quality.md) | Quality (non-functional) requirements |
| [requirements/constraints.md](requirements/constraints.md) | Design constraints for maintainers |

## Rules for maintainers

- Requirements first: a new or changed behaviour is written here, marked
  `Status: proposed`, before any code. The implementing change removes the
  status line, next to updating `AGENTS.md` and `docs/src/`.
- Removed behaviour: delete its items in the change that removes the code.
- Write the requirement as observable behaviour. Code paths belong in `Comment:`
  only when they help find the implementation. Implementation steps belong in an
  untracked `<feature>-plan.md` in the repo root, never here.
- No em-dashes in this directory (project rule).
