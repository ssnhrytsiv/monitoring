# Pydantic Migration Targets

## Admin DAL (`app/DAL/admins_operations.py`)
- Current DTOs use dataclasses: `AdminSnapshot` (id, username, display, tg_id; frozen), `AdminLabel` (display, username).
- Functions returning these DTOs: `get_admin_by_id`, `get_admin_by_tg_id`, `get_admin_label`.
- Call sites that rely on these DTOs:
  - `app/admin_bot/services/admins.py` (returns snapshots from `get_admin_by_id`, passes into subscription flow, uses fields id/username/display/tg_id).
  - `app/admin_bot/services/subscription/refresh_channels_subscription.py` (expects `AdminSnapshot`, constructs one from `m.Admin` when needed, uses id/username/display/tg_id).
  - `app/admin_bot/services/subscription/__init__.py` (re-exports `AdminSnapshot`).
  - `app/sheet_bot/services/gsheets_buffer.py` and `app/notificator_bot/service.py` consume `get_admin_label` (need `.display` or `.username` for labels).
- Pydantic models to add for this module: `AdminSnapshotModel` (immutable), `AdminLabelModel` (simple label DTO).

## Requested DAL (`app/DAL/requested_operations.py`)
- Current DTOs use dataclasses: `InviteCheckRecord` (invite_hash, session, noted_at, next_check_at, tries), `RequestedCheckRecord` (session, channel_id, noted_at, next_check_at, tries).
- Functions returning these DTOs: `due_invites`, `due_requested`.
- Call sites that rely on these DTOs:
  - `app/services/requested_reconciler.py` consumes `due_invites` and `due_requested` results (expects attribute access for invite_hash/session/channel_id/noted_at/next_check_at/tries).
- Pydantic models to add for this module: `InviteCheckRecordModel`, `RequestedCheckRecordModel` (should allow attribute access from ORM rows and keep the same fields as current dataclasses).
