# MARS UI polish review

Reviewed 2026-09-16 against the local README, roadmap, brand notes, all page
components, and the shared UI, editor and theme implementation.

The original review was based on source code. The implementation was subsequently
checked in Chromium with fixture-backed screens and against the deployed console.
Contrast figures in the original findings were calculated from the declared CSS colors.

## Implementation and validation

The recommendations below were implemented on 2026-09-16. Settings now has Access,
Integrations and Data sections; legacy URLs redirect. The account menu includes
Account, appearance and sign-out. Shared styling, list filters, action menus, SQL
workspace layout, copy, contrast, form labels, confirmation dialogs and unsaved-editor
protection have been updated. Catalog duplication now preserves the original schema
and options instead of resetting them to connector defaults.

Validation includes a production frontend build, browser interaction tests with
synthetic API responses, and rendered checks of 12 main screens in both themes at
1440, 768, 390 and 320 px. The accessibility scan found a low-contrast muted label and
phone overflow from hidden action labels; both were corrected and the affected screens
passed a repeat scan. No browser JavaScript errors remain in the checked flows.

The reusable test is `frontend/tests/browser_smoke.py`; its fixture module contains
no live credentials or project data. It checks navigation, old settings URLs, search,
filters, API failures, unsaved changes, keyboard exit from SQL, copying catalog entries,
saving and save errors, cancelled destructive actions, cancelled logout, viewer
permissions, system appearance changes and sign-in. See the README for running it.

The updated console was deployed without recreating the Flink services. All nine
running job IDs and states, plus the Flink container IDs and start times, were
unchanged after deployment. The previous console image is retained locally as
`mars/console:pre-ui-polish-20260916` for rollback. The working-tree changes have not
been committed or pushed.

The original findings follow as a record of the design decisions.

## Direction

Make MARS feel like a compact, carefully maintained operations tool. Keep the orange
mark, neutral palette, tables, plain language, and light/dark/system themes. The
main opportunity is hierarchy: repeated cards, accent strokes, badges and explanatory
paragraphs give unrelated content similar emphasis. The useful information needs a
clearer order and the actions need a consistent home.

## 1. Simplify the application shell

**Evidence:** `frontend/src/components/Layout.jsx` puts seven administrator navigation
items, the expanded product name, three theme buttons, capacity, username and sign-out
in a fixed-height header. The navigation scrolls with its scrollbar hidden. The
Account route has no permanent navigation link; its link appears only in the temporary
password-change banner. The footer repeats the expanded name and product description.

**Proposal:** Keep Jobs, Catalog, Activity and Cluster in the main navigation. Group
Secrets, AI provider, Accounts, Schema registry and Backup under Settings, with the
existing permissions retained. Use an account menu for Account, theme and Sign out.
Keep the compact MARS mark/name in the header; use the README's short product
description on the sign-in screen. Reduce the footer branding. This does not require
deciding the backronym or redesigning the mark.

Give navigation an explicit compact layout on narrow screens rather than allowing
utilities to squeeze the tabs. Make capacity a link to Cluster and label whether the
number represents free or used slots.

## 2. Bring the SQL workspace forward

**Evidence:** `JobEditor.jsx` puts metadata and `PromptPanel` ahead of the statement.
`PromptPanel.jsx` renders a full card even when the feature is disabled. The schema
sidebar is already useful and should remain. `JobDetail.jsx` places validation,
editing, duplication and two stop actions together in the header, while current state
is in a separate sidebar card.

**Proposal:** Use a compact metadata section followed by the SQL workspace. Offer
“Draft with AI” as an expandable tool beside the editor, retaining the existing diff,
validation and explicit application of changes. Hide the disabled feature's full card;
an administrator can configure it through Settings.

Put state and target near the job title. Keep Edit and the current Run/Resume/Stop
action visible. Put Duplicate, Start fresh and Stop without saving in a labeled
More menu, preserving their explanations and confirmations. Keep safe stopping the
default. Consolidate validation and output preview below the statement.

The roadmap's fuller editor component is a later improvement; workspace layout can
improve independently.

## 3. Reduce decorative repetition and improve readability

**Evidence:** `components/ui.jsx` adds a short orange rule under every page title;
`index.css` adds similar ticks to section labels. Cards share borders and shadows
regardless of importance. Healthy running pills pulse indefinitely. Catalog uses two
orange creation buttons, while selected type/kind controls also use primary-button
styling. Tables mix the shared `.tbl` class with separate spacing and type rules.

**Proposal:** Let headings and spacing provide structure. Remove routine title rules
and section ticks; use flat sections with dividers inside forms and retain bordered
panels where they establish a useful boundary. Use static healthy indicators and
reserve motion for work in progress, honoring reduced-motion preferences.

Standardize page headings, section headings, table rows, helper text and controls.
Use 13–14 px for ordinary readable content; keep tiny text for incidental metadata.
Use neutral selected states for source/sink and streaming/batch choices. Give Catalog
one “New entry” action that offers Source or Sink. Keep orange concentrated on primary
actions and active navigation.

Fix theme colors as part of this work. White text on the primary button's `#ea580c`
background calculates to **3.56:1**. Dark-mode info alerts use `#7c2d12` text on
`#2b1a10`, calculating to **1.78:1**: only the brand/accent 50 step changes with the
theme, while several foreground steps remain fixed. Define separate theme-aware
colors for action backgrounds, links, selected text and informational messages.
Use a minimum 4.5:1 acceptance target for ordinary small text in both themes.

## 4. Tighten copy and make lists easier to scan

Keep contextual explanations that help someone make a decision, especially around
savepoints and preview behavior. Move implementation tutorials and repeated feature
introductions into expandable help. Replace conversational labels with direct ones:

| Current | Suggested |
| --- | --- |
| Describe it instead | Draft with AI |
| What actually runs | Execution SQL |
| Show me the output | Preview output |
| What changed? | Change note |
| Saved with this version, so the history reads like a story. | Included in version history. |
| Nothing has gone wrong | No outstanding issues |
| For (Jobs column) | Duration |

Jobs should expose a stable search/filter toolbar, with explicit state filters when
useful; search currently appears only above six jobs. Catalog needs search and a
consistent entry-name link, with duplication and deletion in a row menu. Add clear
column headings to Activity and run history. Remove the empty cluster column when
rows are grouped by cluster.

In Administration, the account-oriented heading and New account button currently
precede unrelated registry and backup panels. Settings subsections would make the
heading, action and visible content agree.

## 5. Finish the interaction details

- `Field` renders a label beside its control without associating them. Connect labels,
  hints and errors to control IDs, and use fieldsets for grouped choices. Give search
  and editor controls accessible names.
- The SQL textarea intercepts Tab, including Shift+Tab, without an explicit keyboard
  escape. Provide a documented way to leave the editor and verify keyboard navigation.
- Page-header action rows do not wrap, and several tables sit inside `overflow-hidden`
  containers. Add responsive toolbars and deliberate table scrolling; verify long job
  names and narrow screens without clipping.
- Jobs replaces the entire list on any polling error, even after data has loaded. Keep
  the last successful list visible with a stale-data notice and retry action.
- Job and Catalog mutation controls are shown without consulting the user's role.
  Align visible controls with API permissions so viewers get a coherent read-only UI.
- Use a shared confirmation dialog for destructive actions, with correct focus handling,
  explicit consequences, pending state and errors. Preserve the existing safeguards.
- Add consistent saved feedback and protection against accidentally leaving unsaved
  editors. The editor's current `dirty` flag tracks SQL validation freshness, so it
  should not be reused as an unsaved-changes indicator.

## Suggested first implementation pass

Start with the shell, shared typography/colors, shorter labels and the editor's AI
disclosure. These changes affect the daily experience without changing pipeline
execution. Follow with table/action consistency and the interaction fixes above.

Validate rendered Jobs, Catalog, Job detail, both editors and Settings in light and
dark themes at desktop, tablet and phone widths. Include long names, empty states,
failures, an unavailable API and a viewer account. Check keyboard navigation and
contrast, and run the frontend production build. Keep this verification separate
from running or stopping production jobs.
