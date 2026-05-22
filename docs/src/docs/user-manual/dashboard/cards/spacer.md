# Spacer Cards

A spacer card is invisible. It takes up space in the grid without displaying anything, letting you push other cards into specific positions or leave deliberate gaps in your layout.

## When to use a spacer

- You want two cards to appear side by side but there is an odd gap between them.
- You want a card to start on the right side of the grid instead of the left.
- You want visual breathing room between groups of cards.

## Basic example

```yaml
type: spacer
positioning:
  position: 5
  width: 2
  height: 1
```

This reserves a 2-column, 1-row slot at position 5. No content appears, but the surrounding cards flow around it as if something were there.

## Fields

Spacer cards only support `type`, `positioning`, and the optional `hide_on` field described below. Fields like `title`, `query`, or `method` are not accepted.

---

## `hide_on`

```yaml
hide_on: mobile
```

Hides the spacer completely on the specified screen size, so it no longer occupies any grid space there.

| Value | Effect |
|---|---|
| *(omitted)* | The spacer is visible on all screen sizes. |
| `mobile` | The spacer disappears on phone screens (grid width 6 columns or less). |
| `desktop` | The spacer disappears on larger screens (grid width more than 6 columns). |

When a spacer is hidden, it is removed from the grid entirely, not just made invisible. Any cards that follow it will shift to fill the freed space.

### Example: gap only on desktop

```yaml
type: spacer
hide_on: mobile
positioning:
  position: 3
  width: 4
  height: 1
```

This pushes cards to the right on desktop, but collapses away on mobile so the smaller screen is not wasted.

## Hover appearance

Although spacers are invisible by default, hovering over one reveals a faint outline so you can see where it is and click the pencil icon to edit or delete it.
