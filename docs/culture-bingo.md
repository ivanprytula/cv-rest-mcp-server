# Company Culture Bingo

Interactive browser game at `/culture-bingo`. Players click tiles to reveal whether
job-posting phrases signal genuine culture or hidden red flags.

## How It Works

- **8x8 grid** (64 cells) with three categories: positive (green), red-flag (red),
  and ambiguous/yellow-flag (yellow).
- **First click** on a cell applies a color overlay based on the cell ID prefix
  (`green-*`, `red-*`, `yellow-*`).
- **Second click** fades the cell out, incrementing the "revealed" counter.
- **Reset** clears all state and reloads the original layout.

Cell order is **randomized server-side** on every page load so the grid never looks
the same twice.

## Endpoints

| Route | Method | Description |
| --- | --- | --- |
| `/culture-bingo` | GET | Renders the game page (HTML) |
| `/api/games/culture-bingo/content` | GET | Returns the raw content JSON |

Both endpoints are rate-limited (`30/min`, `120/hour`).

## Content

Game content lives in `config/bingo_content.json`. The structure:

```json
{
  "title": "Company Culture Bingo",
  "settings": { "gridSize": 8 },
  "cells": [
    { "id": "green-01", "content": "Cell text (title\\nOptional subtitle)" }
  ]
}
```

Cell IDs determine the click color: `green-*` = green, `red-*` = red, `yellow-*` =
yellow. The content JSON is validated at startup; a missing or malformed file causes
a hard startup failure.

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
The game board gradient and cell colors remain consistent; background, text, and
UI chrome adapt to the active theme.

## Files

| File | Purpose |
| --- | --- |
| `config/bingo_content.json` | Game content (cells, settings) |
| `templates/games/culture_bingo.html` | Game page template |
| `app/routes.py` | Route handlers + content loader |
| `tests/test_bingo.py` | Test suite |
