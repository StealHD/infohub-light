## 9. Enforcement and acceptance

Every production UI change must pass, in order:

1. Static UI contract checks, product-documentation merge maintenance, and ESLint import restrictions.
2. TypeScript and Vitest.
3. Vite production build and artifact scan proving no MUI/Emotion modules, `Mui` class markers, deleted preview routes, or deleted comparison copy.
4. Playwright at 1440×900, 1024×768, and 390×844, including persisted manual dark/light choices, Reduced Motion, and Axe with zero serious or critical findings.
5. Nearby/collision-aware Tooltip geometry, Reduced Motion, focus restoration, independent scrolling, sidebar/Agent track continuity, stable ID-plus-offset anchors where required, explicit Feed top resets after sort changes, bounded virtualization, and no horizontal overflow checks.
6. Any source-setup change additionally verifies `/subscriptions` at desktop and 390 px: X/Instagram/YouTube are peer options; unavailable platforms expose no submit action; ready platform forms contain no Apify/Actor/Route/Key/support-check or advanced-JSON text; edit locks preserve metadata fields and focus; the dialog and page have no horizontal overflow.
7. Any ActorOps resilience change additionally verifies `/settings/actorops` at desktop and 390 px across `主备配置 / 来源启用 / 运行与告警`: compatibility risk and 1/3 confirmation, source soft preference, 6–168-hour/disabled freshness authorization, manual-cost confirmation, dedicated-Key blocking, persistent failure memory/retry-once, diagnostic filters, long-reason wrapping, dialog focus restoration, and zero horizontal overflow. `/settings/secrets` must show acquisition/validation roles without exposing a Key value.

The static contract rejects MUI/Emotion imports, production feature-level direct HeroUI imports, nested `DesignSystemProvider` mounts, raw business-page colors, page-level visual constants, business-owned copies of the approved PageFrame widths, and deleted preview technology. Snapshot or expectation changes require an intentional contract change; they are not an automatic response to a failing visual test.
