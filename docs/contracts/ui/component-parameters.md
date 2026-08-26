<!-- init-pro:control schema=3 profile=backend project=inteliscope-infohub-light file=docs/contracts/ui/component-parameters.md -->
# Inteliscope UI Component Parameters

## 1. Default and precedence

- When the user does not name a style, use the current Quiet Studio / graphite-purple system and this matrix.
- HeroUI Pro is a reference for visual hierarchy, density and finished composition. Implement with HeroUI v3 OSS through `frontend/src/design-system/**` and repository-owned code; do not import or copy Pro code.
- A user-requested color or style applies only to the named surface unless the user explicitly requests a global redesign. New colors are allowed; reusable colors and parameters enter the semantic theme once instead of being repeated by pages.
- Accessibility, responsive behavior and product interaction contracts always remain in force. A reference screenshot cannot remove accessible names, focus behavior, Reduced Motion or supported viewports.

## 2. Selection rule

1. Choose the matching role below before adding `className` overrides.
2. Import the primitive or pattern from `src/design-system`; feature code does not import HeroUI directly.
3. Keep parameters owned by the role—typography, target size, padding, radius, icon size and motion—unchanged in feature code. Layout-only width or positioning may remain local when the route contract requires it.
4. If no role fits, add or extend one focused design-system pattern, update this matrix and add its contract test. Do not create a page-local visual system.

## 3. Shared geometry

| Parameter | Value | Owner and use |
| --- | ---: | --- |
| Page header | 52 px track / 44 px surface | `--inteliscope-size-page-header` keeps Shell layout stable; shared `PageHeader` uses the 44 px inset surface while Workbench, Settings and docked panel headers retain their owned 52 px tracks |
| Desktop sidebar footer | 64 px | `--inteliscope-size-sidebar-footer`; account and document controls stay on this fixed bottom track while the rail changes width |
| Compact control | 32 px | icon actions, compact select, view-mode tabs |
| Standard control/row | 40 px | ViewBar, navigation rows and ordinary toolbar targets |
| Coarse-pointer target | at least 44 px | touch versions of interactive controls |
| Page padding | 16 / 24 px | mobile / ≥768 px route content |
| Reading / Settings / Admin / Auth width | 820 / 920 / 1180 / 960 px | `PageFrame` only |
| Panel / Card / Feed card / Table / Control / Compact / status marker radius | 16 / 14 / 18 / 22 / 10 / 8 / 5 px | theme radius tokens only; table and status marker retain their existing geometry |
| Fast / Standard / Disclosure / Deliberate motion | 120 / 160 / 200 / 220 ms | local response / ordinary transition / shared disclosure / surface-layout change |

Ordinary composition uses 4 px for tightly related icon internals, 8 px for controls, 12 px for a component group, 16 px for card padding, 20 px for roomy card sections and 24 px for desktop page padding. A feature may use other layout measurements only for behavior such as virtualization, media aspect ratios or a resizable rail—not to restyle a shared component.

## 4. Component matrix

| Role | Primitive/pattern | Required parameters |
| --- | --- | --- |
| Route frame | `PageFrame` | Select exactly `reading`, `settings`, `admin` or `auth`; page content uses 16 px mobile and 24 px desktop padding. |
| Page header | `PageHeader` or owned Shell header | Shared `PageHeader` occupies a 52 px Shell track with a 44 px surface inset 8 px inline and 4 px block, full thin separator and pill radius; it keeps `type-page-title`, 12 px mobile/16 px desktop content padding, and one aligned action group. Owned Shell headers retain their existing contract unless explicitly changed. |
| Page section | `PageSection` / `SettingsSection` | Section heading uses `type-section-title`; card-local section heading uses `type-page-title`; description uses `type-body`; outer gap 12 px. |
| View toolbar | `ViewBar` / `ScrollAdaptiveViewBar` | At least 40 px high, 4 px internal gap, `type-control`, control radius; the floating form may use the approved pill variant only. |
| Primary action | `Button` default variant | One primary action per action group; `type-control`; 15 px control icon. Do not restyle its height, radius, font or shadow per page. |
| Secondary/destructive action | `Button variant="secondary|ghost|danger"` | Secondary for visible alternatives, ghost for low-emphasis/toolbar actions, danger only for destructive confirmation; `size="sm"` is limited to inline or row actions. |
| Icon-only action | `TooltipTriggerButton` or HeroUI icon-only `Button` | 32 px compact target, 15 px icon, complete accessible name and Tooltip; coarse pointer target reaches at least 44 px. Header toggles may use the existing 34×32 geometry. |
| Field | HeroUI `TextField`/`Input`/`TextArea` | Label and value use `type-control`; help/error copy uses `type-meta` or shared field description; use the HeroUI default field radius and height. |
| Form select | `HeroSelect` or design-system `Select` | Use for ordinary form choices, including notification channel and provider. Keep the shared label, 40 px trigger and focus/option anatomy; feature code does not render native `<select>`. |
| Compact select | `CompactSelect` | 32 px trigger, `type-control`, 12 px indicator; use only in toolbars and high-density rows. |
| Navigation/settings row | shared navigation pattern / `SettingsItem` | At least 40 px row, `type-control` label, `type-body` description, 17 px navigation icon in a 32 px slot; rows do not translate or scale. |
| Sidebar rail | Workbench desktop sidebar | Use a 52 px header, one flexible scrolling navigation region and a fixed 64 px account footer. Its scrollbar gutter is `auto`: it consumes rail space only when navigation truly overflows, while mouse wheel, keyboard and touch scrolling remain available at low heights. The refresh Bootstrap shell mirrors these three tracks with icon/line silhouettes rather than row-sized blocks. A rail may animate width and text visibility, but its account/footer baseline must not move between collapsed and expanded states. |
| Card/group | HeroUI `Card`, `PageSection`, `SettingsCard`, `SettingsGroup` | Semantic surface, thin separator, card radius, 16 px default padding; static content has no glow or heavy shadow. |
| Settings operation card | HeroUI `Card` | Use independent cards for independently managed records or routes: header holds identity and status, content holds the current configuration/metrics, footer holds persistent facts and direct actions. ActorOps Route cards keep the collapsed view to identity/health, main/standby choices, then LKG/metrics/actions; technical detail is lazy, stays inside the card, and only one Route opens at a time. Do not use one large flat card to impersonate several independently actionable records. |
| Log-heavy settings view | HeroUI `Tabs`, `Card`, `StatusIndicator` | Separate high-volume events from the primary configuration cards with a URL-driven tab. An actionable event always shows reason, impact, next step and a safe entry; a normal status never relies on color alone, and recovered events expose confirmation rather than an unnecessary action. |
| Feed card | shared Feed card | 18 px semantic radius, 19 px horizontal and 18 px top content inset; feature actions stay in the shared footer pattern. |
| Status/meta/count | `StatusIndicator`, `MetaTag`, `CountBadge`, `RemovableTag` | Status/meta height ≥22 px with 13 px status icon; count is ≥18 px; removable target is 28 px. Status never relies on color alone. |
| Tabs | HeroUI `Tabs` through design system | `type-control`; text tabs use the shared list anatomy; icon-only view tabs use 32 px targets and 15 px icons. |
| Interactive rich Popover | HeroUI `Popover` with `useHoverPopoverIntent` | Use when a trigger needs an interactive preview such as a marketplace link. Hover and keyboard focus open it; moving between trigger and surface preserves it; leaving the whole region uses the shared standard close timing. Escape, external press and focus exit close it and restore trigger focus; touch uses the existing click toggle. |
| Table | HeroUI `Table` through design system | Table radius, thin border, 44 px header, `type-meta` column labels; overflow stays inside the table scroll container. |
| Settings form dialog | HeroUI `Modal` | `lg` for multi-field forms; one heading in `Modal.Header`, unframed fields in `Modal.Body`, and cancel then primary completion in `Modal.Footer` aligned to the lower right. Do not nest a card or duplicate the dialog heading inside the form. |
| Dialog/drawer | HeroUI `Modal`/`Drawer` | `sm` for confirmation, `lg` for multi-field forms, `type-page-title` heading and `type-body` copy; cancel is ghost, completion is primary or danger. |
| Status placement | `StatusIndicator` / `StatusBadge` | Put a normal Ready/healthy state with the record it qualifies; reserve a group-level status row for a blocked, draining, degraded or unavailable group that changes available actions. Never render a separate success line that repeats every visible record state. |
| Loading/empty/error | shared patterns | `LoadingReveal`, `LoadingState`, `EmptyState`, `StatusNotice` and Toast vocabulary; preserve final geometry and live-region semantics. |

## 5. Icon roles

| Icon role | Size | Examples |
| --- | ---: | --- |
| Status/micro | 13 px | health, running, warning, inline remove/retry state |
| Control/action | 15 px | button, select, search, filter, toolbar and card action |
| Navigation/leading | 17 px | sidebar, Settings item/card and panel heading |
| Prominent/brand | 20 px | product mark or isolated feature emblem; larger artwork needs an explicit component contract |

Lucide glyph choice may vary by meaning, but a component keeps the size assigned to its role. Small optical exceptions such as a 12 px chevron belong inside the owning design-system component rather than becoming a new feature-level scale.

## 6. Review checklist

- The nearest existing production component was reused before creating a new one.
- New or changed typography uses a defined `type-*` role; an existing baseline surface is not restyled merely to rename a class.
- Component-owned dimensions use design-system tokens or patterns, not copied pixel literals.
- Dark/light, desktop/tablet/mobile, keyboard focus, accessible name and Reduced Motion remain correct.
- Visual snapshot changes are intentional consequences of the requested UI change, never an automatic fix for a failing test.
