CREATE TABLE monitors(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin TEXT NOT NULL,
        subset TEXT,
        owner TEXT,
        start_date TEXT NOT NULL,
        cpm REAL NOT NULL,
        created_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'collecting',
        first_found_at TEXT
    );
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE monitor_channels(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        monitor_id INTEGER NOT NULL,
        input TEXT NOT NULL,
        channel_id INTEGER,
        username TEXT,
        title TEXT,
        note TEXT,
        joined INTEGER DEFAULT 0,
        found_msg_id INTEGER,
        found_at TEXT,
        published_at TEXT,
        max_views INTEGER DEFAULT 0,
        views24 INTEGER,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        UNIQUE(monitor_id,input),
        FOREIGN KEY(monitor_id) REFERENCES monitors(id)
    );
CREATE TABLE settings(
        key TEXT PRIMARY KEY,
        value TEXT
    );
CREATE TABLE membership (
  channel_id INTEGER NOT NULL,
  account    TEXT    NOT NULL,
  status     TEXT    NOT NULL, -- joined/already/requested/invalid/private/blocked/too_many
  ts         INTEGER NOT NULL,
  PRIMARY KEY (channel_id, account)
);
CREATE INDEX idx_membership_channel ON membership(channel_id);
CREATE INDEX idx_membership_status  ON membership(status);
CREATE TABLE invite_map (
  invite_hash TEXT PRIMARY KEY,
  channel_id  INTEGER
, title TEXT, updated_at INTEGER);
CREATE TABLE url_cache (
  url    TEXT PRIMARY KEY,
  status TEXT    NOT NULL,       -- joined/already/requested/invalid/private
  ts     INTEGER NOT NULL
);
CREATE INDEX idx_urlcache_status ON url_cache(status);
CREATE TABLE link_queue (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  url           TEXT NOT NULL,
  state         TEXT NOT NULL,            -- queued | processing | done | failed
  tries         INTEGER NOT NULL DEFAULT 0,
  added_ts      INTEGER NOT NULL,
  next_try_ts   INTEGER NOT NULL,
  last_error    TEXT,
  batch_id      TEXT,                     -- опційний тег партії/сеансу
  origin_chat   INTEGER,                  -- звідки прийшло (для нотифів)
  origin_msg    INTEGER
, owner_display TEXT, owner_username TEXT);
CREATE INDEX idx_lq_state_next ON link_queue(state, next_try_ts);
CREATE UNIQUE INDEX uq_lq_url_active
  ON link_queue(url)
  WHERE state IN ('queued','processing');
CREATE TABLE invite_status (
  invite_hash TEXT PRIMARY KEY,
  status      TEXT    NOT NULL,  -- joined/already/requested/invalid/private/blocked/too_many
  ts          INTEGER NOT NULL
);
CREATE TABLE post_watch (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id  INTEGER NOT NULL,
  pattern     TEXT    NOT NULL,
  mode        TEXT    NOT NULL,   -- 'exact' | 'fuzzy'
  threshold   REAL,               -- для fuzzy, напр. 0.70
  created_at  INTEGER NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX idx_postwatch_channel ON post_watch(channel_id);
CREATE INDEX idx_postwatch_active  ON post_watch(active);
CREATE TABLE ad_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_chat_id INTEGER NOT NULL,
            source_message_id INTEGER NOT NULL,
            date_ts INTEGER NOT NULL,
            caption TEXT NOT NULL,
            caption_norm TEXT NOT NULL,
            caption_hash TEXT NOT NULL,
            added_at INTEGER NOT NULL
        );
CREATE INDEX ad_samples_hash_idx ON ad_samples(caption_hash);
CREATE INDEX ad_samples_chat_idx ON ad_samples(source_chat_id);
CREATE TABLE post_template (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  text       TEXT    NOT NULL,
  mode       TEXT    NOT NULL,   -- 'exact' | 'fuzzy'
  threshold  REAL    NOT NULL,   -- 1.0 для exact; 0..1 для fuzzy
  created_at INTEGER NOT NULL
, title TEXT, links TEXT);
CREATE INDEX idx_lq_owner_usr ON link_queue(owner_username);
CREATE TABLE channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT UNIQUE,
            username TEXT,
            title TEXT,
            owner_display TEXT,
            owner_username TEXT,
            last_status TEXT,
            created_at TEXT,
            updated_at TEXT
        );
CREATE TABLE links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id BIGINT,
            raw_url TEXT,
            kind TEXT,
            batch_msg_id BIGINT,
            owner_display TEXT,
            owner_username TEXT,
            added_at TEXT
        );
CREATE INDEX idx_channels_channel_id ON channels(channel_id);
CREATE INDEX idx_channels_owner_usr ON channels(owner_username);
CREATE INDEX idx_channels_owner_disp ON channels(owner_display);
CREATE INDEX idx_links_channel ON links(channel_id);
CREATE INDEX idx_links_owner_usr ON links(owner_username);
CREATE INDEX idx_links_owner_disp ON links(owner_display);
