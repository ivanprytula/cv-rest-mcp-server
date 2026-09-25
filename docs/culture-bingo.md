# Company Culture Bingo

Interactive browser game at `/culture-bingo`. Players click tiles to reveal whether
IT/software job-posting phrases signal genuine engineering culture or hidden red flags.

## How It Works

- **Batched grid** - all cells (64 today: 26 positive/green, 22 red-flag, 16
  ambiguous/yellow) are dealt into batches of `PAGE_SIZE` (20), so a batch is
  finished in 20 clicks, not 128.
- **One click** on a cell reveals its flag: the cell gets a hard-edged **diagonal
  split fill** (flag colour on the top-left half, the base cell colour on the other
  half) based on the cell ID prefix (`green-*`, `red-*`, `yellow-*`), and the
  "revealed" counter increments. A revealed cell is final for the batch - clicking
  it again does nothing, and there is no right-click undo.
- **Batch complete** shows an overlay with *Continue* to the next batch, or
  *Replay from start*. The last batch shows "All cards seen!" instead.
- **Reset this batch** clears the current batch's reveals and keeps the page.
- Progress and the current page are persisted in `localStorage` under
  `bingo_progress_v2`, wiped automatically when the card set changes.

Cell order is **fixed server-side**: cells are interleaved green/red/yellow so every
batch has a mix, then split into stable pages. Page indices are therefore stable
across sessions - a reload (or a "Continue" later) resumes where you left off.

## Endpoints

| Route | Method | Description |
| --- | --- | --- |
| `/culture-bingo` | GET | Renders the game page (HTML) |
| `/api/v1/culture-bingo/cards?page=N` | GET | Returns one page of interleave-ordered cards |

Both endpoints are rate-limited (`30/min`, `120/hour` for the page, `60/min`,
`300/hour` for the cards endpoint).

## Content

Game content lives in `config/bingo_content.json`. The structure:

```json
{
  "title": "Company Culture Bingo",
  "settings": { "gridSize": 8 },
  "cells": [
    { "id": "green-01", "content": "Title*Optional explanation text" }
  ]
}
```

Cell IDs determine the click color: `green-*` = green, `red-*` = red, `yellow-*` =
yellow. The `*` delimiter in content separates the title from an optional explanation;
the explanation renders as `<small>` (hidden on mobile). The content JSON is validated
at startup; a missing or malformed file causes a hard startup failure.

## Responsive Design

The grid adapts across viewports:

| Viewport | Columns | Cell sizing |
| --- | --- | --- |
| Desktop (>= 1024px) | 7 | Auto-height, text wraps |
| Tablet (641-1023px) | 5 | Auto-height |
| Mobile (<= 640px) | 3 | Auto-height, smaller font |

Cell text is always readable; the grid adapts column count rather than shrinking text.

## Theming

The page supports the site-wide light/dark toggle via CSS custom properties.
The game board gradient stays the same, but the split fill is theme-aware so the
cell text stays readable on **both** halves: dark mode uses a deep saturated fill
with light text, light mode a pale tint with dark text (`--fill-*` plus
`--cell-detail-selected`).

## Files

| File | Purpose |
| --- | --- |
| `config/bingo_content.json` | Game content (cells, settings) |
| `services/games/templates/games/culture_bingo.html` | Game page template |
| `services/games/routes.py` | Route handlers + content loader + batch paging |
| `services/games/tests/test_bingo.py` | httpx-level test suite |
| `services/games/tests/test_e2e_bingo.py` | Playwright interaction tests (`-m e2e`) |
