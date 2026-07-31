# Text Selection Highlight Design

## Goal

Make dragged text selections clearly visible across the dark Device Workbench
without making the interface look saturated, playful, or inconsistent with
its professional operations-console palette.

## Final Colors

- Active selection background: `#315F9F`
- Selected text foreground: `#F8FAFC`

The muted cobalt background is distinct from the OLED navy surfaces while
remaining less saturated than a browser-default blue. The selected text has a
contrast ratio of approximately 6.14:1 against the selection background. The
selection background has approximately 3.14:1 contrast against the terminal
background.

## Scope

Apply the same text-selection colors to:

- xterm terminal output;
- Canvas terminal output;
- Legacy `QPlainTextEdit` terminal output;
- command record editor;
- search, address, username, password, and other Qt text inputs;
- selectable text in embedded workspace web pages.

Do not change selection colors for device rows, cards, terminal tabs, group
tabs, checked buttons, or other non-text selection states.

## Implementation

- Add dedicated text-selection foreground and background tokens instead of
  reusing the existing general `selected` surface token.
- Add the tokens to `theme_tokens.py` and the shared workspace web theme.
- Use the tokens for xterm's `selectionBackground` and
  `selectionForeground` theme properties.
- Use the same colors in `TerminalCanvasWidget` selection painting.
- Add a final Qt stylesheet cascade for editable/selectable text controls so
  earlier component-specific selection declarations cannot override it.
- Add a shared web `::selection` rule for native browser text selection.

The selection uses a flat fill with no glow, gradient, animation, outline, or
layout change. Focus loss does not reduce it to a low-contrast gray.

## Testing

- Verify all three terminal renderers use the dedicated tokens.
- Verify Qt text controls end with the approved selection colors.
- Verify web pages define the shared native selection rule.
- Run syntax checks, focused style tests, the existing regression suite, and
  a visual screenshot check before restarting the desktop application.
