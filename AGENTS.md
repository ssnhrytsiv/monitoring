# MANDATORY RULES FOR THIS REPO

## Architecture
- All DB access must be inside app/DAL/** only.
- Business logic must not import SessionLocal, engine, Base, or ORM models for querying.
- Business logic may call DAL functions only.
- Functions must exchange structured objects with named fields (pydantic/dataclasses/ORM rows); do not pass tuples/lists/None blobs that require positional unpacking in business logic.

## Single source of DB configuration
- The ONLY place that defines/creates engine, SessionLocal and Base is app.db.session (session.py re-exports).
- DAL must import SessionLocal ONLY from app.db.session.
- Never create new engines, sessions, or Base anywhere else.
- Alembic is the single source of truth for schema and migrations.

## SQL / ORM rules
- No query construction in business logic (no session.query, select, execute, or SQL strings).
- No raw SQL strings outside app/DAL/**.
- No f-strings in SQL anywhere; parameterized queries only.
- DAL may use SQLAlchemy ORM or Core, but only inside app/DAL/**.
- DAL functions must manage sessions internally (open, commit/rollback, close).
- DAL must never return a session, query, or ORM query object to business logic.

## Naming — Code
- Variable, function, class, and field names must be explicit and descriptive.
- No abbreviations or short forms: no ctx, cfg, tmp, obj, data, res, req, dto, etc.
- Names must describe the real business meaning of the object.
- Prefer longer, clear names over short or ambiguous ones.

## Naming — Database
- Column and table names must reflect the real domain concept.
- Use full words: channel_id, watch_post_status, matched_at, deleted_at, source_url.
- Do not use generic or abbreviated names like id2, val, info, data, tmp, cfg.
- Timestamps must be suffixed with _at (created_at, updated_at, matched_at, deleted_at, expired_at).
- Boolean fields must be prefixed with is_ or has_ (is_active, has_error).

## Naming — DAL
- DAL functions must use explicit verbs and domain nouns:
  - get_watch_by_id
  - list_channel_watches
  - create_watch_post
  - update_watch_status
  - mark_post_as_deleted
- Do not use generic names like process, handle, do, run, update1, getData.

## Behavior
- Refactors must not change business behavior.
- Keep public interfaces in business layer stable unless explicitly requested.

## Output
- Produce unified diff patches only.
- No inline comments inside code blocks.
