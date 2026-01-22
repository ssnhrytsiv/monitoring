You are Codex with full access to this repository.

MIGRATION MODE: A2 (DAL manages sessions internally, no db passed from services/listeners)

TASK:
Refactor EXACTLY 3 DAL functions to remove the `db: Session` argument and manage `session_scope()` internally.
Then update ALL call sites across the repository for these 3 functions.
Do NOT refactor any other functions.

STRICT RULES:
- Do NOT change business behavior.
- Do NOT add wrapper functions.
- Do NOT add new modules.
- Keep function names unchanged.
- Keep return types unchanged.
- Output UNIFIED DIFF ONLY.

TARGET FUNCTIONS (EXACTLY THESE 3):
1) app/DAL/watch_processing_operations.py::list_due_coverage_db
2) app/DAL/watch_processing_operations.py::mark_done_views_db
3) app/DAL/watch_events_operations.py::insert_watch_event

REFRACTOR RULES:
- Convert each target function from:
    def func(db: Session, ...):
  to:
    def func(...):
        with session_scope() as db:
            ...
- Import session_scope ONLY from app.db.session (single source of DB config).
- Remove `Session` imports if unused after refactor.
- If any of these functions contain db.commit(), remove it (session_scope commits automatically).
- Do not call db.commit()/db.rollback() inside session_scope blocks; session_scope handles commit/rollback on exit.

CALL SITE UPDATE:
- Replace any call:
    func(db, a, b, ...)
  with:
    func(a, b, ...)
- Remove surrounding `with session_scope() as db:` blocks ONLY if they were used exclusively for calling these functions.
- If the session_scope block also contains other DB work, keep it and only update the call.

VALIDATION:
- Exactly 3 function signatures changed.
- No remaining call passes `db` into these 3 functions.

OUTPUT:
Unified diff patch only.
