---
applyTo: "web/**,scripts/build-*.sh"
---

# Client Instructions

- Preserve the existing Vite + React web structure; reuse current API/state patterns instead of adding parallel client abstractions.
- If a change affects API fields, auth state, route behavior, Markdown/chart rendering, local backend startup, or report payloads, assess Web compatibility.
- Validate Web changes with `cd web && npm ci && npm run lint && npm run build` when feasible.
