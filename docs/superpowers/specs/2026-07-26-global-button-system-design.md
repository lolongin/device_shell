# Global Button System Design

## Goal

Unify every application button around one compact professional design system
while preserving clear differences between actions, navigation, tabs, toggles,
and destructive operations.

## Design Tokens

### Regular buttons

- Height: 28 pixels.
- Corner radius: 6 pixels.
- Horizontal padding: 10 pixels.
- Minimum readable text size: 12 pixels.

### Compact buttons

- Height: 24 pixels.
- Corner radius: 5 pixels.
- Horizontal padding: 8 pixels.

### Icon buttons

- Standard icon control: 24 by 24 pixels.
- Activity-rail navigation: 34 by 34 pixels.
- Icons use a consistent 14- to 16-pixel visual size.

## Color and State Rules

- Default:
  - Background: `#08101d`.
  - Border: `#243244`.
  - Text/icon: `#a7b4c7`.
- Hover:
  - Background: `#111c2f`.
  - Border: `#60a5fa`.
  - Text/icon: `#f8fafc`.
- Pressed:
  - Background becomes darker than hover.
  - Border remains visible.
  - No scale or geometry change is used.
- Focus:
  - Blue focus border using `#60a5fa`.
  - Focus remains visible for keyboard users.
- Selected or checked:
  - Background: `#163326`.
  - Border: `#22c55e`.
  - Text/icon: `#d8fff0`.
- Primary:
  - Green filled treatment reserved for connect, send, confirm, and start
    actions.
- Danger:
  - Neutral default presentation.
  - Red background, border, and text appear on hover or confirmed destructive
    state.
- Disabled:
  - Background remains within the dark surface family.
  - Border and text contrast are reduced.
  - Disabled controls remain visibly distinct from enabled controls.

## Button Roles

The application uses the following roles:

- `primary`: connection, confirmation, start, and send actions.
- `secondary`: ordinary bordered actions.
- `ghost`: low-emphasis utility actions.
- `danger`: delete, disconnect, stop, and clear actions.
- `toggle`: filters, mode switches, and checked controls.
- `tab`: terminal and command-group navigation.
- `icon`: icon-only toolbar actions.
- `rail`: activity-rail navigation.

Existing object names and semantic properties map to these roles. The final
style layer becomes the single source of truth, replacing conflicting visual
values from earlier style blocks.

## Special Components

### Tabs

- Tabs use the compact 24-pixel height and shared state colors.
- Selected tabs use the selected/checked treatment.
- Close buttons remain icon-only and reveal the danger treatment on hover.
- Adding a tab uses the same icon-button geometry.

### Terminal command footer

- Command-group tabs, add/close controls, broadcast, send, and clear actions
  share the compact height and radius.
- Send is primary.
- Broadcast is secondary.
- Clear is danger with a neutral default.

### Activity rail

- Rail buttons retain their larger 34-pixel square hit area.
- Their border, hover, selected, focus, and disabled states use the global
  colors.

### Connection cards and forms

- Connect buttons use the primary role.
- Edit, collapse, refresh, and similar actions use secondary or ghost roles.
- Disabled protocol actions use the global disabled treatment.

## Implementation Structure

- Add a final, clearly named `Global button system` section to `APP_STYLE`.
- Consolidate role selectors in that final section so later rules cannot
  produce inconsistent geometry or state colors.
- Add semantic properties only where an existing object name does not express
  the required role, especially the command-footer actions.
- Avoid unrelated layout or behavior changes.

## Accessibility and Interaction

- Hover and pressed states do not move or resize controls.
- Keyboard focus remains visible.
- Text and icons retain readable contrast in the dark theme.
- Dangerous actions are not identified by color alone; labels and icons
  continue to communicate their purpose.
- Disabled actions are visually distinct and remain non-interactive.

## Verification

Automated tests cover:

- Global style tokens and state selectors exist.
- Primary, danger, selected, disabled, and focus roles are represented.
- Command-footer actions receive the correct semantic role.
- Tab and icon-button geometry remains compact.
- Activity-rail buttons retain the 34-pixel hit area.

Manual verification covers:

- Home/device filters and toolbar actions.
- Activity rail and tool panels.
- Connection cards and protocol actions.
- Terminal tabs and quick-action toolbar.
- Command record tabs, footer actions, and find/replace controls.
- Disabled, checked, hover, pressed, and keyboard-focus states.
