# Contest Problem PDF Generator — UI/UX Design Specification

**Version:** 1.0  
**Application:** `notion-to-pdf`  
**Audience:** UI Designers, UX Designers  
**Source:** Derived from Technical Specification v2.0

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Users & Context](#2-users--context)
3. [Application Structure](#3-application-structure)
4. [Page Inventory](#4-page-inventory)
5. [Screen: Login (Browser Native)](#5-screen-login-browser-native)
6. [Screen: Main Application Page](#6-screen-main-application-page)
   - 6.1 [Page Header](#61-page-header)
   - 6.2 [Toolbar Bar](#62-toolbar-bar)
   - 6.3 [Problem List](#63-problem-list)
   - 6.4 [Problem Card](#64-problem-card)
   - 6.5 [Bundle Progress Modal / Overlay](#65-bundle-progress-modal--overlay)
   - 6.6 [Warning & Error Panel](#66-warning--error-panel)
7. [Component Inventory](#7-component-inventory)
8. [States & Feedback Model](#8-states--feedback-model)
9. [Data Fields Reference](#9-data-fields-reference)
10. [User Flows](#10-user-flows)
    - 10.1 [Flow A: Download a Single PDF](#101-flow-a-download-a-single-pdf)
    - 10.2 [Flow B: Download a ZIP Bundle](#102-flow-b-download-a-zip-bundle)
    - 10.3 [Flow C: Force Re-fetch a Single Problem](#103-flow-c-force-re-fetch-a-single-problem)
    - 10.4 [Flow D: Clear All Cache](#104-flow-d-clear-all-cache)
    - 10.5 [Flow E: Search / Filter Problems](#105-flow-e-search--filter-problems)
    - 10.6 [Flow F: Encountering Warnings](#106-flow-f-encountering-warnings)
    - 10.7 [Flow G: Encountering a Hard Error](#107-flow-g-encountering-a-hard-error)
11. [Interaction Details & Edge Cases](#11-interaction-details--edge-cases)
12. [Content & Copy](#12-content--copy)
13. [Constraints for Designers](#13-constraints-for-designers)

---

## 1. Product Overview

This is an **internal web tool** used by a small contest organising team (1–3 people) to convert programming contest problem statements from Notion into correctly formatted PDFs, ready for printing and distributing at the contest.

The team writes problems in Notion. When they are ready to produce contest materials, they open this tool, select the problems they want, and download a ZIP of PDFs — or download individual PDFs one at a time. The tool handles all formatting, font rendering, bilingual titles, math notation, and image embedding automatically.

### Core Value Proposition

> One click per problem to download a print-ready PDF. No LaTeX, no formatting, no credential sharing.

### What this tool is NOT

- Not a Notion editor or viewer.
- Not a PDF viewer (PDFs go directly to the browser download dialog).
- Not a contest management system.
- Not designed for public-facing use. It is password-protected.

---

## 2. Users & Context

### Primary User

**Contest Organiser / Problem Setter**

- Small team of 1–3 people.
- Technically literate but not necessarily developers.
- Uses the tool in the days/hours before a contest to prepare printable materials.
- May be under time pressure — reliability and clear feedback are more important than visual polish.
- Uses a **desktop or laptop browser** (no mobile requirement).
- Logs in with a shared team username/password.
- Expects the tool to "just work" after login — no onboarding, no tutorial needed.

### Usage Pattern

- **Infrequent but high-stakes.** The tool may be used only a handful of times per contest, but those uses happen right before the contest starts. Errors or confusing UI at that moment are costly.
- **Small dataset.** Typically 7–8 problems in the active list, up to ~20 in the full database.
- **Repeat downloads.** Users may download the same problem multiple times as problem setters iterate on the Notion content. Cache status and refresh controls are important.

---

## 3. Application Structure

There is a **single page** in this application. Everything happens on one screen. There is no routing, no navigation, no settings page.

```
Browser URL: https://your.domain.com/
                        │
                        ▼
              [Browser Login Dialog]  ← HTTP Basic Auth (browser native)
                        │
                        ▼
              [Main Application Page]  ← The only screen
                        │
          ┌─────────────┼──────────────┐
          ▼             ▼              ▼
      [Header]     [Toolbar]     [Problem List]
    logo, title   search, bulk    scrollable cards
    warnings,     controls, ZIP
    cache clear   button
```

---

## 4. Page Inventory

| Screen | Description | Notes |
|---|---|---|
| Login | Browser's native HTTP Basic Auth dialog | Not designed by us — handled by the browser |
| Main Page | The only application screen | All features live here |

There are no sub-pages, modals (except the bundle progress overlay), or navigation.

---

## 5. Screen: Login (Browser Native)

The login is handled entirely by the browser's built-in HTTP Basic Auth dialog. The application does not render a custom login screen.

**What the user sees:** The browser shows a small popup/dialog with two fields: username and password.

- **Username:** Always `team` (fixed, shared)
- **Password:** Set by the administrator via `APP_PASSWORD` environment variable

**Design implication:** We have no control over the login UI. The first screen we own is the main application page after successful login.

**Failed login:** The browser repeats the dialog. After multiple failures, the browser shows its own error. We do not show a custom error.

---

## 6. Screen: Main Application Page

This is the entire application. It has four distinct regions:

```
┌──────────────────────────────────────────────────────────────────┐
│  HEADER                                                          │
│  [App title / branding]    [⚠ Warning Panel]   [Clear Cache]    │
├──────────────────────────────────────────────────────────────────┤
│  TOOLBAR                                                         │
│  [Search box]   [Select All / Deselect All]   [Bundle: N / M]  │
│                                               [Download ZIP ▼]  │
├──────────────────────────────────────────────────────────────────┤
│  PROBLEM LIST                                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PROBLEM CARD                                             │   │
│  │ [☐] [A]  กลับบ้าน (Place To Call Home)   [Medium] [↺][⬇]│   │
│  │          1 second · 256 MB                              │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ PROBLEM CARD                                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ... (more cards)                                               │
└──────────────────────────────────────────────────────────────────┘
```

---

### 6.1 Page Header

**Location:** Fixed at the top of the page. Always visible when scrolling.

**Purpose:** Branding, global controls, and the persistent warning panel.

#### Elements

| Element | Description | Behaviour |
|---|---|---|
| App title | e.g. "Contest PDF Generator" or the contest name | Static text. Contest name comes from server config (`CONTEST_NAME`). |
| Warning Panel trigger | A badge/button showing the count of accumulated warnings and errors | Clicking it expands/collapses the Warning & Error Panel (see §6.6). If zero warnings, the trigger is hidden or greyed out. |
| "Clear All Cache" button | A button to invalidate all cached PDFs | Calls `DELETE /api/problems/cache`. On success shows a brief confirmation. Does not reload the problem list. |

#### States

| State | Appearance |
|---|---|
| No warnings | Warning trigger is hidden or visually suppressed |
| 1+ warnings | Warning trigger shows a count badge (e.g. "⚠ 3") with a warning colour (amber/orange) |
| 1+ errors | Warning trigger shows a count badge with an error colour (red) |
| Mixed warnings + errors | Use the most severe colour (red) |

---

### 6.2 Toolbar Bar

**Location:** Directly below the header. Stays near the top (either sticky or close enough that the user doesn't need to scroll far).

**Purpose:** Search, bulk selection controls, and the bundle download action.

#### Elements

| Element | Type | Description |
|---|---|---|
| Search box | Text input | Filters the visible problem list client-side. Matches against problem title (both Thai and English parts). Placeholder text: "Search problems…" |
| Select All | Button / link | Checks all currently visible problem checkboxes (respects current search filter). Label toggles to "Deselect All" when all visible problems are checked. |
| Selection counter | Text | Shows "Bundle: N / M selected" where N = checked count, M = total visible. Updates instantly as checkboxes change. |
| Download ZIP button | Primary action button | Initiates bundle generation. Disabled (with tooltip) when N = 0. Active and visually prominent when N ≥ 1. |

#### Download ZIP Button States

| State | Appearance | Behaviour |
|---|---|---|
| 0 problems selected | Greyed out, not clickable | Tooltip: "Select at least one problem" |
| 1+ problems selected | Active, primary colour | Clickable. Opens progress overlay. |
| Generating (in progress) | Replaced by progress indicator | See §6.5 |
| Complete | Returns to normal | Browser file download triggers automatically |

---

### 6.3 Problem List

**Location:** Below the toolbar. Scrollable.

**Purpose:** Display all problems fetched from Notion, one card per problem.

#### Loading State

When the page first loads, the problem list is empty and a **loading indicator** is shown while `GET /api/problems` completes.

- Show a spinner or skeleton cards.
- Typical load time: 1–3 seconds (Notion API fetch).

#### Empty State

If `GET /api/problems` returns an empty array (or the search filter returns zero results):

- **No problems from server:** Show a message: "No problems found in the Notion database." Include a note that the database may be empty or filtered by status.
- **No search results:** Show: "No problems match your search."

#### Error State

If `GET /api/problems` fails (network error, server error):

- Show a clear error message with a **Retry** button.
- Do not show an empty list silently.

#### Sort Order

Problems are displayed sorted by:
1. Problem Letter (A → Z)
2. Then by Name (alphabetically)
3. Problems without a letter appear at the bottom

The sort order is determined server-side. The UI does not need to implement sorting.

---

### 6.4 Problem Card

Each card represents one contest problem. This is the most important UI element.

#### Layout

```
┌──────────────────────────────────────────────────────────────────┐
│  [☐]  [A]  กลับบ้าน (Place To Call Home)        [Medium]        │
│            1 second · 256 MB                    [↺ Refresh] [⬇ PDF] │
└──────────────────────────────────────────────────────────────────┘
```

#### Elements

| Element | Description | Notes |
|---|---|---|
| Checkbox | Selects this problem for bundle inclusion | Unchecked on load. State lives in browser JS memory only — not persisted. |
| Letter badge | Shows the problem letter: A, B, C… | Displayed as a badge/pill. If no letter is set, omit or show a dash. |
| Title (Thai) | Thai portion of the bilingual title (e.g. `กลับบ้าน`) | Displayed prominently. Primary display title. |
| Title (English) | English portion in parentheses (e.g. `Place To Call Home`) | Displayed as secondary text, either inline or below the Thai title. |
| Time limit | e.g. "1 second" | Displayed as metadata below the title. |
| Memory limit | e.g. "256 MB" | Displayed alongside time limit. |
| Difficulty badge | e.g. "Easy", "Medium", "Hard" | Displayed as a coloured badge. Colour coding: Easy = green, Medium = amber, Hard = red. May be absent if not set in Notion. |
| Status | e.g. "Draft", "Ready" | Optional. May be displayed as a secondary badge if present. Does not control bundle inclusion. |
| "↺ Refresh" button | Clears the cached PDF for this problem | Icon button. Calls `DELETE /api/problems/<id>/cache`. See states below. |
| "⬇ PDF" button | Downloads a single-problem PDF | Calls `GET /api/problems/<id>/pdf`. See states below. |

#### Cache Status Indicator

The UI should communicate whether a cached PDF exists for a problem. Suggested approach:

- A small indicator (dot, icon, or label) on the card when a cached version exists.
- This helps users know if their download will be instant (cache hit) or will take a few seconds (cache miss).
- After the user downloads a PDF, the card should show "cached" state.
- After clicking "↺ Refresh", the card should show "not cached" state.

#### "⬇ PDF" Button States

| State | Appearance | Behaviour |
|---|---|---|
| Idle (not cached) | Normal button | On click: starts download, button shows loading state |
| Idle (cached) | Normal button, possibly with a cache indicator | On click: instant download from cache |
| Loading | Spinner / "Generating…" label | Button disabled during generation. Typical duration: 1–5 seconds. |
| Done | Returns to normal | Browser file download triggers. If warnings exist, warning banner appears. |
| Error | Button returns to normal, error added to warning panel | Do not leave button in a broken state. |

#### "↺ Refresh" Button States

| State | Appearance | Behaviour |
|---|---|---|
| Idle | Icon button | On click: calls cache-clear endpoint, then updates cache indicator |
| Loading | Spinner | Brief — the cache clear is fast (no Notion call) |
| Done | Returns to idle. Cache indicator updates to "not cached". | |
| Error | Icon button. Error added to warning panel. | |

#### Warning Indicator on Card

If a PDF was downloaded and came back with warnings (via `X-PDF-Warnings` header), the card should display a small warning indicator (e.g. ⚠ icon) to remind the user that this problem had issues. Clicking it should surface the specific warnings in the warning panel.

---

### 6.5 Bundle Progress Modal / Overlay

**Triggered by:** Clicking "Download ZIP" with 1+ problems selected.

**Purpose:** Show real-time progress of PDF generation across all selected problems, since the process takes 30–80 seconds total.

**Mechanism:** The browser opens a Server-Sent Events connection to the server. Progress events arrive one by one as each PDF is generated.

#### Layout

```
┌──────────────────────────────────────────────────────┐
│  Generating ZIP Bundle                               │
│                                                      │
│  Generating Problem B: เส้นทางสั้นที่สุด…            │
│                                                      │
│  ████████████░░░░░░░░░░░░░░░░░░   3 / 8             │
│                                                      │
│  ✓ Problem A: กลับบ้าน                               │
│  ✓ Problem B: เส้นทางสั้นที่สุด                      │
│  ⚠ Problem C: ... (1 warning)                        │
│  … (remaining)                                       │
│                                                      │
│                              [Cancel]                │
└──────────────────────────────────────────────────────┘
```

#### Elements

| Element | Description |
|---|---|
| Title | "Generating ZIP Bundle" |
| Current problem label | "Generating [Problem Letter]: [Thai Title]…" — updates per SSE event |
| Progress bar | Visual fill from 0 to 100%. Increments after each problem completes. |
| Progress counter | "N / M" where N = completed, M = total selected |
| Completed problem list | A running log of completed problems with status icons: ✓ (ok), ⚠ (warning), ✗ (error) |
| Cancel button | Allows the user to abort. Closes the SSE connection. No partial ZIP is downloaded. |

#### States

| State | Appearance |
|---|---|
| Starting | Progress bar at 0. "Preparing…" label. |
| In progress | Progress bar fills incrementally. Current problem name updates. Completed list grows. |
| Complete (no warnings) | Progress bar full. "Done! Downloading…" message. ZIP download triggers automatically. Overlay auto-closes after ~2 seconds or on user dismissal. |
| Complete (with warnings) | Progress bar full. "Done with warnings." message in amber. ZIP still downloads. Overlay stays open longer so user can read warnings. |
| Error (one problem failed) | That problem marked ✗ in completed list. Generation continues for remaining problems. |
| Fatal error (SSE connection dropped) | Show an error message. "Download ZIP" button becomes available again. |
| Cancelled | Overlay closes. No download. |

#### Behaviour After Completion

1. When the SSE stream emits `{"status": "done", "token": "..."}`, the UI automatically triggers a file download using the token.
2. Any warnings collected during the run are added to the persistent Warning & Error Panel.
3. The overlay should remain open long enough for the user to see the final status before auto-closing (suggest: auto-close after 3 seconds if no warnings; keep open if warnings so user can read them).

---

### 6.6 Warning & Error Panel

**Location:** Anchored to the page header. Collapsible — collapsed by default.

**Purpose:** Accumulate all warnings and errors from the current session. Since users may download multiple problems in sequence, this panel acts as a running log so nothing gets lost.

**Key behaviour:** The panel is **never auto-cleared**. Entries only disappear when the user explicitly dismisses them. The session log resets on page refresh (intentional — the state lives in JS memory).

#### When it appears / grows

| Trigger | Entry added |
|---|---|
| PDF downloaded with `X-PDF-Warnings` header | One entry per warning code |
| Bundle generated with warnings on individual problems | One entry per warning per problem |
| API call returns HTTP 500 | One error entry |
| SSE connection dropped unexpectedly | One error entry |
| Problem list fails to load | One error entry |

#### Warning codes and human-readable messages

| Warning code | Display message |
|---|---|
| `missing_image:<filename>` | "⚠ [Problem Title]: An image could not be downloaded and was skipped. The PDF may have a gap where the image should appear." |
| `unknown_section:<heading>` | "⚠ [Problem Title]: The section heading "[heading]" was not recognised and its content was excluded from the PDF. Check the Notion page." |

#### Layout of a single entry

```
┌────────────────────────────────────────────────────────────┐
│ ⚠  Problem A: กลับบ้าน                                    [✕]│
│    An image could not be downloaded and was skipped.         │
│    The PDF may have a gap where the image should appear.     │
└────────────────────────────────────────────────────────────┘
```

| Element | Description |
|---|---|
| Severity icon | ⚠ for warnings (amber), ✗ for errors (red) |
| Problem title | Which problem this warning relates to |
| Message | Human-readable explanation (see table above) |
| Dismiss button [✕] | Removes this single entry from the panel |

#### Header trigger button

When the panel has entries, the header shows a button like **"⚠ 3 Warnings"** (or **"✗ 1 Error, ⚠ 2 Warnings"**). Clicking this toggles the panel open/closed.

When the panel is empty: hide the trigger or show it greyed out / disabled.

---

## 7. Component Inventory

A complete list of all interactive and display components required.

| Component | Type | Used in |
|---|---|---|
| Problem card | Compound component | Problem list |
| Checkbox | Input | Problem card |
| Letter badge | Display badge | Problem card |
| Difficulty badge | Display badge (coloured) | Problem card |
| Status badge | Display badge | Problem card |
| Cache indicator | Status indicator (dot/icon) | Problem card |
| "⬇ PDF" button | Action button with loading state | Problem card |
| "↺ Refresh" button | Icon button with loading state | Problem card |
| Warning indicator on card | Inline icon | Problem card |
| Search box | Text input | Toolbar |
| Select All / Deselect All | Toggle button | Toolbar |
| Selection counter | Text display | Toolbar |
| "Download ZIP" button | Primary action button, disabled state | Toolbar |
| "Clear All Cache" button | Secondary action button | Header |
| Warning panel trigger | Badge button | Header |
| Warning panel | Collapsible panel | Header |
| Warning entry | List item with dismiss | Warning panel |
| Loading spinner / skeleton | Loading state | Problem list |
| Empty state illustration | Placeholder | Problem list |
| Error state | Inline error with retry | Problem list |
| Bundle progress overlay | Modal / overlay | Full-screen on bundle action |
| Progress bar | Animated fill bar | Bundle overlay |
| Completed problems log | Scrollable list | Bundle overlay |
| Toast / confirmation | Transient notification | Cache clear confirmation |

---

## 8. States & Feedback Model

### Page-Level Loading States

| Moment | What to show |
|---|---|
| Page first loads, problem list fetching | Skeleton cards or spinner in the list area |
| Problem list loaded | Cards render |
| Problem list load fails | Inline error with Retry button |

### Per-Problem States

Every problem card independently cycles through states. The following matrix covers all combinations:

| Scenario | PDF Button | Refresh Button | Cache Indicator | Card Warning Icon |
|---|---|---|---|---|
| Just loaded, no cache | Normal | Normal | "Not cached" (or hidden) | Hidden |
| Just loaded, cache exists | Normal | Normal | "Cached" indicator | Hidden |
| PDF generating | Spinner, disabled | Disabled | Unchanged | Hidden |
| PDF downloaded, no warnings | Normal | Normal | "Cached" | Hidden |
| PDF downloaded, with warnings | Normal | Normal | "Cached" | ⚠ visible |
| Refresh clicked, clearing | Normal | Spinner, disabled | Unchanged | Unchanged |
| Refresh complete | Normal | Normal | "Not cached" | Unchanged |
| PDF download failed | Normal (returned) | Normal | Unchanged | ✗ visible (error) |

### Bundle States

| Moment | Download ZIP button | Toolbar counter | Overlay |
|---|---|---|---|
| 0 selected | Disabled | "Bundle: 0 / 8 selected" | Hidden |
| 1+ selected | Enabled | "Bundle: N / M selected" | Hidden |
| Bundle generating | — (overlay takes focus) | Unchanged | Visible, in-progress |
| Bundle complete | Enabled (reset) | Unchanged | Auto-closing or dismissed |
| Bundle error | Enabled (reset) | Unchanged | Shows error, stays open |

---

## 9. Data Fields Reference

Every field that appears in the UI, where it comes from, and how to handle missing or edge-case values.

| Field | Source | Display location | If missing / empty |
|---|---|---|---|
| Thai title | Notion `Name` property (part before parenthesis) | Card — primary title | Show full title as-is |
| English title | Notion `Name` property (part inside parentheses) | Card — secondary title; ZIP filename | Show full title as-is |
| Full title | Notion `Name` property | PDF title, bundle SSE progress label | Never missing — required field |
| Problem letter | Notion `Problem Letter` property | Card letter badge; PDF title prefix | Omit badge; problem sorted to bottom of list |
| Time limit | Notion `Time Limit` property | Card metadata | Default: "1 second" |
| Memory limit | Notion `Memory Limit` property | Card metadata | Default: "256 MB" |
| Difficulty | Notion `Difficulty` select property | Card difficulty badge | Omit badge |
| Status | Notion `Status` select property | Card status badge (informational only) | Omit badge |
| last_edited_time | Notion API metadata | Not displayed; used for cache logic | Never missing |
| Warning codes | `X-PDF-Warnings` response header | Warning panel, card warning icon | No warnings — nominal case |

### Title display format

If the title is `กลับบ้าน (Place To Call Home)`:
- **Primary (large):** `กลับบ้าน`
- **Secondary (small):** `Place To Call Home`

If the title has no parenthetical (e.g. `Two Sum`):
- **Primary (large):** `Two Sum`
- No secondary title.

---

## 10. User Flows

### 10.1 Flow A: Download a Single PDF

**Goal:** Download the PDF for one specific problem.

```
1. User opens the app (already logged in).
2. Page loads → problem list populates.
3. User finds the problem (via scroll or search).
4. User clicks "⬇ PDF" on the problem card.
5. Button shows loading state ("Generating…" or spinner).
   → Server checks cache:
      [Cache HIT]  → PDF returned in ~0 seconds
      [Cache MISS] → PDF generated in 1–5 seconds
6. Browser download dialog appears → user saves PDF.
7. If warnings: warning banner appears on the card + entry added to panel.
8. Button returns to normal state. Card shows "Cached" indicator.
```

**Happy path duration:** 0–5 seconds.

**Error path:** If generation fails, button returns to normal and an error entry appears in the warning panel.

---

### 10.2 Flow B: Download a ZIP Bundle

**Goal:** Download PDFs for multiple problems in one ZIP file.

```
1. User opens the app (already logged in).
2. Page loads → problem list populates.
3. User selects problems using checkboxes:
   - May use "Select All" to check everything visible.
   - May search first to filter, then "Select All" the filtered set.
   - Counter updates: "Bundle: 5 / 8 selected"
4. User clicks "Download ZIP" button.
5. Bundle progress overlay appears.
6. Progress bar starts at 0. "Preparing…"
7. Server generates PDFs one by one:
   - After each: progress bar increments, completed list grows, current label updates.
   - SSE events: {"done": N, "total": M, "current": "Title", "status": "ok|warning"}
8. Generation complete:
   - Final event includes a download token.
   - Browser automatically downloads the ZIP file.
   - If warnings: overlay shows "Done with warnings."
9. Overlay auto-closes (or user dismisses it).
10. All warnings added to the persistent warning panel.
```

**Happy path duration:** 30–80 seconds for ~8 problems.

**Cancellation:** User can click "Cancel" at any time. SSE connection closes. No ZIP is downloaded.

---

### 10.3 Flow C: Force Re-fetch a Single Problem

**Goal:** Force the server to re-generate a problem's PDF (e.g. because the problem was edited in Notion since it was last generated).

```
1. User sees a problem card with "Cached" indicator.
2. User clicks "↺ Refresh" button.
3. Button shows loading state briefly (cache-clear is fast).
4. Cache entry is deleted server-side.
5. Card's "Cached" indicator disappears / shows "Not cached".
6. User then clicks "⬇ PDF" as normal.
   → PDF is re-generated from Notion (cache miss path).
```

**Note for designers:** The refresh button does NOT automatically download a new PDF. It only clears the cache. The user must click "⬇ PDF" afterwards. This is intentional — the user may want to clear cache for multiple problems before downloading them.

**Alternative path:** If the Notion `last_edited_time` has changed, the server automatically invalidates the cache without the user needing to click Refresh. Refresh is only needed if the user knows content changed but `last_edited_time` hasn't yet been reflected (rare edge case).

---

### 10.4 Flow D: Clear All Cache

**Goal:** Invalidate all cached PDFs at once (e.g. after a round of edits in Notion).

```
1. User clicks "Clear All Cache" in the header.
2. A confirmation may be shown (optional — "Clear cache for all N problems?").
3. Server deletes all cache entries. Returns count cleared.
4. Brief confirmation toast: "Cache cleared (8 entries removed)."
5. All card "Cached" indicators reset to "Not cached".
```

**Note for designers:** This does not reload the problem list — only cache state changes. The page does not refresh.

---

### 10.5 Flow E: Search / Filter Problems

**Goal:** Find a specific problem quickly.

```
1. User types in the search box.
2. Problem list filters instantly (client-side, no server call).
3. Cards that match the search remain visible. Non-matching cards are hidden.
4. Selection counter updates: "Bundle: 2 / 3 selected" (denominator = visible count).
5. "Select All" / "Deselect All" acts only on visible (filtered) cards.
6. User clears the search box → all problems reappear.
```

**Search matching:** Matches against both the Thai and English parts of the title. Case-insensitive.

---

### 10.6 Flow F: Encountering Warnings

**Goal:** User understands that a PDF was generated but has non-fatal issues.

```
[During single PDF download]
1. PDF downloads successfully.
2. Browser reads X-PDF-Warnings header.
3. A ⚠ icon appears on the problem card.
4. The warning panel trigger in the header updates: "⚠ 1 Warning".
5. User can click the trigger to expand the panel and read the details.

[During bundle generation]
1. A problem in the bundle SSE stream returns "status": "warning".
2. That problem in the completed log shows ⚠ instead of ✓.
3. When the bundle completes, the overlay shows "Done with warnings."
4. All warnings are added to the persistent panel.
5. Warning trigger in header updates to reflect total count.
```

**Key principle:** Warnings do NOT block the PDF from downloading. The PDF is delivered even if warnings exist. The user is informed but not blocked.

---

### 10.7 Flow G: Encountering a Hard Error

**Goal:** User understands that something failed and what to do.

```
[Problem list fails to load]
1. Instead of problem cards, show an error message.
2. Show a "Retry" button that re-calls GET /api/problems.

[Single PDF generation fails]
1. "⬇ PDF" button returns to normal state.
2. Error entry added to warning panel with ✗ icon.
3. User can try again by clicking "⬇ PDF" again.

[Bundle SSE connection drops]
1. Overlay shows an error message.
2. Progress bar stops.
3. "Cancel" button changes to "Close".
4. No ZIP is downloaded (even if some PDFs completed).
5. User can retry from scratch by closing the overlay and clicking "Download ZIP" again.
```

---

## 11. Interaction Details & Edge Cases

### Checkbox behaviour with search active

- If the user searches, then clicks "Select All", only the **visible (filtered)** problems are selected.
- Problems hidden by the search filter retain their previous selection state (checked/unchecked).
- When the search is cleared, previously hidden but selected problems reappear still checked.
- The counter always reflects: "selected visible / total visible".

### "Select All" toggle label

- If all visible cards are checked → show "Deselect All".
- If any visible card is unchecked → show "Select All".
- The label updates immediately as individual checkboxes are toggled.

### Download ZIP with a mix of cached and uncached problems

- The bundle generates PDFs one at a time regardless of cache state.
- Cached problems complete nearly instantly; uncached ones take 1–5 seconds each.
- The progress bar and completed list still update per-problem, so cached ones appear to "fly through" quickly.
- No special UI distinction needed — the user sees progress either way.

### Problem edited in Notion between page load and PDF download

- If the user opens the page, then someone edits a problem in Notion, then the user downloads that problem's PDF: the server uses `last_edited_time` from the `/api/problems` call at page-load time as the cache key. If the cache entry was created with an older `last_edited_time`, the new PDF will be generated fresh (cache miss), and the new `last_edited_time` is used as the new cache key.
- The user does not need to do anything special. However, they will not see the new `last_edited_time` unless they reload the page. This is acceptable — the user can always click "↺ Refresh" to force a re-fetch.

### Very long Thai titles

- Cards should handle long titles gracefully — truncate with ellipsis or wrap. Do not let long titles break the card layout.
- The full title should be accessible (e.g. via tooltip on hover or by wrapping onto a second line).

### Problems without a difficulty badge

- Simply omit the badge. Do not show "Unknown" or a placeholder.

### Problems without a letter

- Omit the letter badge entirely (do not show a dash or empty circle).
- These problems appear at the bottom of the list.

### Zero problems in the database

- Show the empty state illustration with the message: "No problems found in the Notion database."

### Warning panel with many entries

- The panel should be scrollable if it has many entries.
- Consider a "Dismiss All" button at the top of the panel when there are more than ~5 entries.

---

## 12. Content & Copy

All user-facing strings in the application.

### Labels & Buttons

| Element | Copy |
|---|---|
| App title | "Contest PDF Generator" (or use `CONTEST_NAME` value) |
| Search placeholder | "Search problems…" |
| Select All | "Select All" |
| Deselect All | "Deselect All" |
| Selection counter | "Bundle: {N} / {M} selected" |
| Download ZIP (0 selected) | "Download ZIP" (disabled) |
| Download ZIP (1+ selected) | "Download ZIP" |
| Download ZIP tooltip (0 selected) | "Select at least one problem to download" |
| Single PDF button | "⬇ PDF" |
| Single PDF button (loading) | "Generating…" |
| Refresh button label / tooltip | "Re-fetch from Notion" |
| Clear All Cache button | "Clear All Cache" |
| Warning panel trigger (no warnings) | Hidden or "No warnings" (greyed) |
| Warning panel trigger (warnings) | "⚠ {N} Warning{s}" |
| Warning panel trigger (errors) | "✗ {N} Error{s}" or "✗ {E} Error{s}, ⚠ {W} Warning{s}" |

### Bundle Overlay Copy

| Element | Copy |
|---|---|
| Overlay title | "Generating ZIP Bundle" |
| Generating label | "Generating {letter}: {Thai title}…" |
| Starting state | "Preparing…" |
| Progress counter | "{N} / {M}" |
| Complete (no warnings) | "Done! Downloading your ZIP…" |
| Complete (with warnings) | "Done — with {N} warning{s}. Check the warning panel." |
| Cancel button | "Cancel" |
| Close button (after error) | "Close" |

### Warning Messages

| Code | Message |
|---|---|
| `missing_image:<filename>` | "An image could not be downloaded and was skipped. The PDF may have a gap where the image should appear." |
| `unknown_section:<heading>` | "The section heading "{heading}" was not recognised and its content was excluded from the PDF. Verify the Notion page uses the correct heading text." |
| Generic error | "An unexpected error occurred while generating this PDF. Check the server logs for details." |

### Empty & Error States

| State | Copy |
|---|---|
| Problem list loading | "Loading problems from Notion…" |
| Problem list empty | "No problems found in the Notion database." |
| Problem list error | "Could not load problems. Check your connection and try again." |
| No search results | "No problems match "{query}"." |
| Cache cleared confirmation | "Cache cleared — {N} entries removed." |
| Cache clear error | "Could not clear cache. Try again." |

---

## 13. Constraints for Designers

These are hard requirements from the technical specification that the design must accommodate.

### Must-haves

1. **Single page.** There is no routing. Everything happens on one URL. No page navigation.

2. **Desktop-only layout.** Users are on desktop or laptop browsers. Mobile is not a requirement. Design for a minimum width of ~1024px.

3. **Bilingual titles are always present.** Every title has a Thai part and potentially an English part. The layout must accommodate both. Thai text is the primary title; English is secondary.

4. **Progress feedback is mandatory for the bundle.** The bundle takes 30–80 seconds. A simple "loading…" spinner is not sufficient. The overlay with per-problem progress is required.

5. **Warning panel must persist and accumulate.** Warnings are never auto-dismissed. The panel must survive multiple PDF downloads in the same session without clearing.

6. **"Download ZIP" must be disabled when no problems are selected.** This is not optional — sending a bundle request with zero problems is an error condition.

7. **"↺ Refresh" does not download the PDF.** It only clears the cache. Design must not imply that clicking it will produce a download. The user must then click "⬇ PDF" separately.

8. **Cache state lives in JS memory only.** Selection state and cache indicators reset on page refresh. Do not promise persistence.

9. **The login screen is the browser's native HTTP Basic Auth dialog.** We do not design or control it.

10. **No settings page.** There is no settings UI. All configuration is handled by the server administrator via environment variables before deployment.

### Nice-to-haves (not in scope unless explicitly scoped in)

- Dark mode
- Mobile layout
- Keyboard shortcuts
- Drag-to-reorder problems
- Problem preview (in-browser HTML preview — extension described in the technical spec but not required for v1)
- Pagination (the list is expected to be at most ~20 items)
