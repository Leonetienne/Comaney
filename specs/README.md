# Comaney Requirements Database

This directory is the single source of requirements for Comaney. It describes the
system as built: every requirement here is meant to hold for the current code. It
replaces the former loose `*-spec.md` design documents, whose still-valid content
has been folded in.

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
"Shall" marks a binding requirement. "Should" is not used: everything here is as-built.

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

- A feature change updates the affected requirements in the same change, next to
  `AGENTS.md` and `docs/src/`.
- New features get a `feat` item plus their requirements before or with the code.
- Write the requirement as observable behaviour. Code paths belong in `Comment:`
  only when they help find the implementation.
- No em-dashes in this directory (project rule).
