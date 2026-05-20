---
name: feedback_offline_member_label
description: Always append "(offline member)" to a user's name whenever they are an offline/dummy user in UI text
metadata:
  type: feedback
---

Always append `(offline member)` to a user's display name whenever that user is an offline (dummy) user in any UI text, dialog, or message.

**Why:** Offline users have no real-world presence in the app; labelling them keeps messages unambiguous.
**How to apply:** Any time a dummy user's name is interpolated into a user-visible string, add `(offline member)` after the name. Applies to modal dialogs, flash messages, confirmation prompts, and similar UI copy.
