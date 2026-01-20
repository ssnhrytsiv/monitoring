# Refresh Channels Refactor Plan (DAL/DTO/Service/Handler)

Goal: make `refresh_channels_for_admin` and `finalize_refresh_confirmation` an “etalon” flow:

- no DB access in handlers
- no `await` inside `with session_scope() as db:`
- no ORM objects crossing async/await boundaries
- DAL returns DTO/primitives; business logic works with named fields only
- no SQLite locks caused by long/parallel transactions

This file is the single source of truth for progress. After each step is completed, mark it as done and append a short note to the Progress Log.

## Current Status

- Admin DTO: `AdminSnapshot` is defined in DAL (`app/DAL/admins_operations.py`). ✅
- Refresh service: `refresh_channels_for_admin` now follows phased flow (DB read → async batch → DB plan build → async messaging) via `RefreshContext`; DB does not cross async boundaries. ✅
- Pending: add TTL/fingerprint/idempotency for confirmation and move UI helpers out of service.

## Non-Negotiable Invariants

- No `await` inside any `with session_scope() as db:` block.
- No ORM objects are stored or passed outside DAL/DB blocks (no ORM in FSM, caches, globals, pending-confirmations).
- Handlers (aiogram) do not touch DB (no `session_scope`, no DAL calls).
- Service returns only DTO/primitives; Presenter/UI renders strings.
- No “mitigation” fixes (no retries/backoff/sleeps for `database is locked`). Architectural fix only.

## Target Contracts

### Service API

- `refresh_channels_for_admin(refresh_context: RefreshContext) -> RefreshOutcome | None`
- `finalize_refresh_confirmation(batch_id: str, approve_unsubscribe: bool, reply_msg) -> None`

### DTO

- `RefreshContext`: `batch_id, chat_id, reply_msg_ref, admin_id, urls, raw_text, raw_html, entities`
- `BatchResultDTO`: list of items with named fields: `original_url, clean_url, channel_id, title, status_raw, session_hint`
- `RefreshPlanDTO`:
  - `admin_id`
  - `current_cids: set[int]`
  - `keep_cids: set[int]`
  - `to_remove: set[int]`
  - `status_items: list[StatusItemDTO]` (no HTML strings required; presenter will render)
  - `removed_items: list[RemovedItemDTO]`
  - `conflict_clear_cids: set[int]`
  - `no_cid_resolution: bool`
  - `needs_confirmation: bool`
  - `fingerprint: str`
  - `created_at: int`

### Pending Confirmations Storage

- `_PENDING_REFRESH_CONFIRMATIONS[batch_id]` stores only primitives/DTO-serializable dict:
  - `admin_id, plan_dict, fingerprint, created_at`
- Add TTL check (e.g., 10–30 minutes) and fingerprint check on confirm.
- Confirm/apply must be idempotent (double-click safe).

## Steps

### 0) Plan File

- [x] Create this plan file.

### 1) Remove DB From Handler Trigger (Refresh)

- [x] Update `app/admin_bot/bot/handlers/admins.py` refresh link collector (`on_refresh_links`) to resolve admin via service/DAL (no `session_scope`).
- [x] Update `app/admin_bot/bot/handlers/admins.py` refresh trigger (`cb_refresh_collect_go`) to:
  - store only `admin_id` in FSM/state
  - call service method (no `session_scope` in handler)
  - start refresh using `RefreshContext` (or `admin_id` only)

### 2) Refactor `refresh_channels_for_admin` Into Phases (No DB Across Await)

- [x] In `app/admin_bot/services/subscription/refresh_channels_subscription.py`, rewrite as phased flow:
  - Phase A (DB-only): read `current_cids` via DAL in one `session_scope` block → close
  - Phase B (async-only): enqueue + `await process_batch(...)` → produce `BatchResultDTO` (no DB)
  - Phase C (DB-only): compute keep/remove + load metadata via DAL (batch reads only) → build `RefreshPlanDTO` → close
  - Phase D (async-only): send preview or final report using Presenter (no DB)
- [x] Remove all `db.close()` calls from this function.
- [x] Ensure no variable named `db` is used outside its `with session_scope()` block.
- [x] Ensure there are no DB queries inside loops over `urls` (batch DAL reads only).

### 3) Refactor `finalize_refresh_confirmation` (No Await Inside DB Blocks)

- [ ] Rewrite `finalize_refresh_confirmation` so that:
  - validate pending data: TTL + fingerprint
  - DB-only block executes apply (unsubscribe/cleanup) using DAL
  - async-only part sends messages
- [ ] Remove any `with session_scope()` that wraps `await` calls.
- [ ] Make confirm/apply idempotent:
  - safe if callback pressed twice
  - if already applied/expired → respond with a short message

### 4) Refactor Cleanup/Unsubscribe (Avoid SQLite Locks)

- [ ] Make cleanup a phased flow:
  - DB-only: compute delete set + gather URLs for cleanup + persist plan
  - async-only: (if needed) external side effects
  - DB-only: perform deletes/updates via DAL
  - async-only: report
- [ ] Ensure cleanup deletes cache rows that cause incorrect fast-path:
  - [x] `invite_cache` cleanup for removed channels
  - `url_cache` cleanup for removed channel URLs
- [ ] Ensure all deletes/queries used by cleanup live in DAL (no raw `m.delete_*` calls in service).

### 5) Move UI Helpers to Utils/Presenter (Keep Service Focused)

- [ ] Move `_FilteredBot`/`_FilteredMessage` wrapper out of service to `app/admin_bot/services/subscription/subscription_utils.py` (or similar).
- [ ] Move `_human_status` and other rendering helpers to Presenter/util.
- [ ] Service returns `StatusItemDTO` etc.; Presenter renders HTML/text.

### 6) DAL Coverage: Add Missing Read Helpers (DTO/Primitives Only)

- [ ] Add/adjust DAL helpers needed by refresh to avoid service-level SQL:
  - bulk URL normalization / mapping helpers
  - batch `channel_id -> title/owner/admin` lookups
  - batch membership account/session hints for a set of channels
  - batch removed-item link metadata (invite_hash/last_raw_url/title)
- [ ] Ensure every DAL helper returns dataclasses with named fields, not tuples.

### 7) Cleanup Imports + Type Safety

- [ ] Remove duplicate imports and dead code in refresh service.
- [ ] Ensure all long-lived caches (`_PENDING_REFRESH_CONFIRMATIONS`) store only primitives/DTO.

### 8) BatchResult Contract (Single Source of Truth)

- [ ] Introduce `BatchResultDTO` as the single source of per-URL outcomes.
- [ ] Service must not “pull statuses” from multiple caches in a loop; instead:
  - adapt `batch_cache` to `BatchResultDTO` once
  - use DAL only for missing metadata (title/memberships/conflicts) in batch

### 9) Guardrails: Enforce Invariants

- [ ] Add a lightweight guard (CI grep or pre-commit) for this flow:
  - disallow `await` inside `with session_scope()` blocks in refresh service module
- [ ] Add structured logs by phase:
  - A: current_cids_count
  - B: batch_items_count + duration
  - C: keep/remove counts + no_cid_resolution
  - APPLY: removed_count

## Definition of Done

- `refresh_channels_for_admin` contains no `db.close()` and no DB session survives across `await`.
- No handler contains DB queries/select/execute.
- All DB reads/writes for refresh are delegated to DAL functions.
- No ORM object is stored in FSM/global caches or used after an `await`.
- Pending confirmation has TTL + fingerprint and confirm/apply is idempotent.
- Phase C uses batch DAL reads only (no DB queries inside URL/channel loops).
- No retries/backoff/sleeps are used to “solve” SQLite locks.

## Progress Log

- 2026-01-20: Step 0 done — plan created.
- 2026-01-20: Step 1 (partial) — `on_refresh_links` now resolves admin via service/DAL (no `session_scope` in handler).
- 2026-01-20: Step 4 (partial) — `invite_cache` cleanup for removed channels added in refresh cleanup.
- 2026-01-20: Step 1 (done) — `cb_refresh_collect_go` now uses service admin snapshot (no handler DB).
- 2026-01-20: Step 2A-1 — `refresh_channels_for_admin` now має рівно два `session_scope()` блоки (до і після `process_batch`), `db.close()` вилучені.
- 2026-01-20: Step 2A-2 — другий `session_scope` у `refresh_channels_for_admin` не містить `await`; усі async-дiї винесені назовні.
- 2026-01-20: Step 2B — прибрано дублікати/невикористані імпорти у `refresh_channels_subscription.py` (поведінка без змін).
- 2026-01-20: Step 3A — `finalize_refresh_confirmation` більше не має `await` у `session_scope`, застосування/звіт робляться поза DB-блоком.
- 2026-01-20: Step 4A — `_cleanup_removed_channels` розбито на фази: DB gather → async leave → DB apply → link_queue cleanup (немає await у `session_scope`).
- 2026-01-21: Phase C оптимізовано пакетними DAL-хелперами (немає SQL у циклі), додано batch DTO (BatchResultDTO, RefreshPlanDTO) і bulk lookup для meta/conflicts/memberships.
- 2026-01-21: Bulk-хелпери для refresh зібрані в `app/DAL/refresh_links_operation.py` (titles/admins/conflicts/memberships/link_meta, invite_cache_status_get_bulk).
- 2026-01-21: Step 2 done — `refresh_channels_for_admin` приймає `RefreshContext`, розбито на фази A–D (DB read → async batch → DB plan build → async preview/report), DB не переходить через await.

## Codex Prompt (Copy/Paste)

Refactor refresh flow to be an “etalon”:

- Target functions: `refresh_channels_for_admin`, `finalize_refresh_confirmation`
- No DB access in handlers; handlers call services only.
- No `await` inside `with session_scope() as db:`
- No ORM objects crossing async boundaries (use DTO snapshots from DAL only).
- Prefer reusing existing DAL functions; if a DB query exists in service, move it to DAL and return DTO/primitives.

Steps to implement:

1) `app/admin_bot/bot/handlers/admins.py`: remove `session_scope()` from `cb_refresh_collect_go` and resolve `AdminSnapshot` via service/DAL.
2) `app/admin_bot/services/subscription/refresh_channels_subscription.py`: split `refresh_channels_for_admin` into phases (DB-only reads → async batch → DB-only plan build → async messaging). Remove `db.close()` calls.
3) `app/admin_bot/services/subscription/refresh_channels_subscription.py`: refactor `finalize_refresh_confirmation` so no DB block wraps any `await`.
4) Cleanup/unsubscribe: make it phased (DB-only gather → async leave → DB-only deletes/commit → async final message). Ensure removed channels clear `invite_cache` and `url_cache` via DAL helpers.

Finer-grained substeps:

- 2A-1: In `refresh_channels_for_admin` keep exactly two `session_scope()` blocks (before and after `await process_batch`) and remove all `db.close()`.
- 2A-2: Ensure the second `session_scope` block has no `await` inside (sync DAL calls only).
- 2B: Clean duplicate imports/unused vars in `refresh_channels_subscription.py` without behavior changes. ✅
- 3A: `finalize_refresh_confirmation` — restructure to DB-read block → async send → DB-apply block (if approve) → async send; no `await` inside `session_scope`, no `db.close()`. ✅
- 4A: `_cleanup_removed_channels` — phase it: DB gather → async `leave_channels` → DB delete → async report; no `await` inside `session_scope`. ✅
- 4B: Ensure `url_cache` cleanup for removed channels on all paths (not just one). ✅

Definition of done:

- No `db` variable used after an `await` in refresh flow.
- No handler performs DB queries/select/execute.
- All refresh DB operations live in DAL and return DTO/primitives only.
