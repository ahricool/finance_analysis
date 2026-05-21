---
applyTo: "web/**"
---

# Client Instructions

- Preserve the existing Vite + React web structure; reuse current API/state patterns instead of adding parallel client abstractions.
- If a change affects API fields, auth state, route behavior, Markdown/chart rendering, local backend startup, or report payloads, assess Web compatibility.
- Validate Web changes with `cd web && pnpm install --frozen-lockfile && pnpm run lint && pnpm run build` when feasible.
