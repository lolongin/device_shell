# Responsive Device Table Sequence Column Design

## Goal

Keep the sequence column visible at every device-table density so users can
identify and reference rows consistently while resizing the left sidebar.

## Column Rules

- Full density at 520 pixels or wider:
  `序号 | 设备 | 板类型 | CPU | Slot | 状态`
- Medium density from 340 through 519 pixels:
  `序号 | 设备 | 板类型 | CPU | 状态`
- Compact density below 340 pixels:
  `序号 | 设备 | 状态`

Only Slot is removed at medium density. Board type, CPU, and Slot are removed
at compact density.

## Width Behavior

- Sequence remains fixed and compact, targeting 58 pixels in full density and
  no less than 52 pixels in narrower densities.
- Status remains fixed and readable.
- Device consumes the remaining width.
- Other visible columns shrink to their configured minimums before horizontal
  scrolling is introduced.

## Group Rows

- Group titles continue to start in the first visible column.
- Because sequence is always visible, group titles start in the sequence
  column and span all visible non-status columns.
- Group counts remain in the status column for full and medium density.
- Compact density keeps the group count in the group-row tooltip.

## Verification

Automated tests cover:

- Sequence is visible in full, medium, and compact density.
- Medium density hides only Slot.
- Compact density shows sequence, device, and status.
- Group-row spans and tooltips remain correct at compact density.
