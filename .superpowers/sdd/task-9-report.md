# Task 9 Implementation Report

## Result

Implemented the permission-aware assistant connection UI without changing the local Gateway boundary, `/mcp` request behavior, shell navigation, or Task 10+ artifacts.

- Agent delegation types now expose `access`, canonical read/write scopes, and `subscription_writes_enabled`.
- `createAgentDelegation(name, access = 'read')` always posts both `name` and `access`.
- The create dialog resets to read access on every open. Viewers never receive the write option; members/administrators/owners see it disabled with explanatory copy while the server flag is off.
- Each connection displays a `只读` or `可管理订阅` Chip and can copy a configuration generated from its own stored access.
- Page-level configuration remains read-only. One-time configuration uses the newly created connection access.
- Read configurations contain the exact six existing tools; write configurations contain those six plus the exact eight Task 8 tools.
- Configuration always uses `Bearer ${INTELISCOPE_MCP_TOKEN}` and never embeds the returned token.
- One-time local state is `{ token, access }`; clicking `我已保存` clears the whole credential object. It is not placed in React Query, URL, or browser storage.

The UI states explicitly that subscription-management access cannot manage secrets, shared sources, jobs, Feed item state, or refreshes.

## TDD Evidence

The requested focused command initially reported 7 failures and 4 passes. The failures matched the missing access POST body, access selector/default, permission Chip, flag-disabled explanation, 14-tool configuration, and per-connection configuration action.

After the minimal implementation:

```text
npm --prefix frontend test -- --run src/api/service.test.ts src/features/agents/AgentsPage.test.tsx
Test Files  2 passed (2)
Tests       11 passed (11)
```

The tightened AgentsPage assertions for exact 6/14 tool arrays and the opened viewer selector also passed 9/9.

```text
npm --prefix frontend run typecheck
tsc -b --pretty false
exit 0
```

## Deferred Boundary

Per the Task 9 light-verification instruction, build, Playwright/E2E, Axe, full gate, mobile-bottom-navigation assertions, and forbidden local-probe assertions were not run or edited. Task 11 owns those final acceptance checks. Task 10 and later product work were not implemented.
