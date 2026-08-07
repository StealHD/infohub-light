## 9. Enforcement and acceptance

Every production UI change must pass, in order:

1. Static UI contract checks, product-documentation merge maintenance, and ESLint import restrictions.
2. TypeScript and Vitest.
3. Vite production build and artifact scan proving no MUI/Emotion modules, `Mui` class markers, deleted preview routes, or deleted comparison copy.
4. Playwright at 1440×900, 1024×768, and 390×844, including persisted manual dark/light choices, Reduced Motion, and Axe with zero serious or critical findings.
5. Nearby/collision-aware Tooltip geometry, Reduced Motion, focus restoration, independent scrolling, sidebar/Agent track continuity, stable ID-plus-offset anchors where required, explicit Feed top resets after sort changes, bounded virtualization, and no horizontal overflow checks.

The static contract rejects MUI/Emotion imports, production feature-level direct HeroUI imports, nested `DesignSystemProvider` mounts, raw business-page colors, page-level visual constants, business-owned copies of the approved PageFrame widths, and deleted preview technology. Snapshot or expectation changes require an intentional contract change; they are not an automatic response to a failing visual test.
