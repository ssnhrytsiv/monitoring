-- Після рефакторингу формує 6 колонок у порядку:
-- 1) title              -> "Назва канала"
-- 2) links_all          -> "Посилання" (лише URL, без first/last/tries)
-- 3) admin_text         -> "Адмін"
-- 4) duplicates_names   -> "Дублікати" (ЛИШЕ display name'и, по одному в рядок)
-- 5) notes              -> "Нотатки"
-- 6) channel_id         -> "ID Канала" (прихований у Google Sheets)

WITH
invites_cl AS (
  SELECT l.channel_id, l.url_norm AS url, NULL AS first_seen_ts, NULL AS last_seen_ts
  FROM links l
  WHERE l.url_norm LIKE 'https://t.me/+%'
),
invites_map AS (
  SELECT ic.channel_id, 'https://t.me/' || '+' || ic.invite_hash AS url, NULL AS first_seen_ts, NULL AS last_seen_ts
  FROM invite_cache ic
  WHERE ic.channel_id IS NOT NULL
),
invites_union AS (
  SELECT channel_id, url, MIN(first_seen_ts) AS first_ts, MAX(last_seen_ts) AS last_ts
  FROM (
    SELECT channel_id, url, first_seen_ts, last_seen_ts FROM invites_cl
    UNION ALL
    SELECT channel_id, url, first_seen_ts, last_seen_ts FROM invites_map
  )
  GROUP BY channel_id, url
),
tries_per_url AS (
  SELECT l.channel_id,
         l.raw_url AS url,
         COUNT(*) AS tries,
         MIN(strftime('%s', NULLIF(l.added_at, ''))) AS first_try_ts,
         MAX(strftime('%s', NULLIF(l.added_at, ''))) AS last_try_ts
  FROM links l
  WHERE l.raw_url LIKE 'https://t.me/+%'
  GROUP BY l.channel_id, l.raw_url
),
tries_norm AS (
  SELECT t.channel_id, t.url, t.tries, t.first_try_ts, t.last_try_ts
  FROM tries_per_url t
),
invites_full AS (
  SELECT iu.channel_id,
         iu.url,
         COALESCE(iu.first_ts, tn.first_try_ts) AS first_ts,
         COALESCE(iu.last_ts,  tn.last_try_ts)  AS last_ts,
         COALESCE(tn.tries, 0)                   AS tries
  FROM invites_union iu
  LEFT JOIN tries_norm tn
    ON tn.channel_id = iu.channel_id AND LOWER(tn.url) = LOWER(iu.url)
),
-- ТІЛЬКИ УНІКАЛЬНІ URL-и
links_agg AS (
  SELECT
    u.channel_id,
    COUNT(*) AS links_count,
    GROUP_CONCAT(u.url, CHAR(10)) AS links_all
  FROM (
    SELECT DISTINCT channel_id, url
    FROM invites_full
  ) AS u
  GROUP BY u.channel_id
),

-- Кандидати у власники (за invite_owners), НОВИЙ пріоритет owner_key: DISPLAY -> USERNAME
owner_candidates AS (
  SELECT
    ic.channel_id,
    LOWER(REPLACE(COALESCE(NULLIF(io.owner_username, ''), io.owner_username), '@', '')) AS owner_key,
    MAX(io.owner_username) AS owner_username,
    COUNT(*)               AS tries,
    MIN(strftime('%s', NULLIF(io.created_at, ''))) AS first_ts,
    MAX(strftime('%s', NULLIF(io.created_at, ''))) AS last_ts
  FROM invite_cache ic
  JOIN invite_owners io ON io.invite_hash = ic.invite_hash
  WHERE ic.channel_id IS NOT NULL
  GROUP BY ic.channel_id, owner_key
),

-- Офіційні конфлікти: нормалізуємо ключ і РЕЗОЛВИМО channel_id (бо у owner_conflicts може бути id або channel_id)
owner_conflicts_by_key AS (
  SELECT
    COALESCE(c_by_id.channel_id, c_by_ch.channel_id, oc.channel_id) AS channel_id,
    LOWER(REPLACE(oc.owner, '@', '')) AS owner_key,
    COUNT(*) AS conflicts,
    MAX(oc.created_at) AS last_conflict_ts,
    -- display з owner_conflicts.owner, якщо виглядає як display (не починається з '@')
    MAX(CASE WHEN TRIM(oc.owner) <> '' AND oc.owner NOT LIKE '@%' THEN oc.owner END) AS display_from_conflicts
  FROM owner_conflicts oc
  LEFT JOIN channels c_by_id
    ON c_by_id.id = oc.channel_id
  LEFT JOIN channels c_by_ch
    ON c_by_ch.channel_id = oc.channel_id
  GROUP BY
    COALESCE(c_by_id.channel_id, c_by_ch.channel_id, oc.channel_id),
    owner_key
),

-- Дублікати (офіційні): ЛИШЕ display name, беремо з owner_candidates, інакше fallback з owner_conflicts
conflicts_names_official AS (
  SELECT
    s.channel_id,
    GROUP_CONCAT(s.name, CHAR(10)) AS names
  FROM (
    SELECT DISTINCT
      obk.channel_id,
      COALESCE(NULLIF(TRIM(cand.owner_username), ''), NULLIF(TRIM(obk.display_from_conflicts), '')) AS name
    FROM owner_conflicts_by_key obk
    LEFT JOIN owner_candidates cand
      ON cand.channel_id = obk.channel_id AND cand.owner_key = obk.owner_key
    WHERE obk.conflicts > 0
  ) AS s
  WHERE s.name IS NOT NULL AND TRIM(s.name) <> ''
  GROUP BY s.channel_id
),

-- Похідні дублі: якщо офіційних немає — показуємо канали з >1 різним owner_key (з display у candidates)
channels_with_derived_conflict AS (
  SELECT channel_id
  FROM owner_candidates
  GROUP BY channel_id
  HAVING COUNT(DISTINCT owner_key) > 1
),
conflicts_names_derived AS (
  SELECT
    s.channel_id,
    GROUP_CONCAT(s.name, CHAR(10)) AS names
  FROM (
    SELECT DISTINCT
      oc.channel_id,
      NULLIF(TRIM(oc.owner_username), '') AS name
    FROM owner_candidates oc
    JOIN channels_with_derived_conflict d
      ON d.channel_id = oc.channel_id
    WHERE NULLIF(TRIM(oc.owner_username), '') IS NOT NULL
  ) AS s
  GROUP BY s.channel_id
),

-- fallback: останній кандидат без конфліктів (для admin_text)
fallback_owner AS (
  SELECT DISTINCT
    oce.channel_id,
    FIRST_VALUE(ece.owner_username) OVER w AS owner_username,
    FIRST_VALUE(ece.owner_username)  OVER w AS owner_username
  FROM owner_candidates AS ece
  JOIN owner_candidates AS oce
    ON oce.channel_id = ece.channel_id
  LEFT JOIN owner_conflicts_by_key obk
    ON obk.channel_id = oce.channel_id AND obk.owner_key = oce.owner_key
  WHERE COALESCE(obk.conflicts,0) = 0
  WINDOW w AS (
    PARTITION BY oce.channel_id
    ORDER BY oce.last_ts DESC
    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
  )
),

-- Остаточний Адмін: channels.* або fallback
owner_final AS (
  SELECT
    c.channel_id,
    COALESCE(NULLIF(c.owner_username,''), fb.owner_username, '') AS owner_username,
    COALESCE(NULLIF(c.owner_username,''), fb.owner_username,  '') AS owner_username
  FROM channels c
  LEFT JOIN fallback_owner fb ON fb.channel_id = c.channel_id
)

SELECT
  c.title                                                          AS title,
  COALESCE(la.links_all, '')                                       AS links_all,      -- тільки URL-и, кожен з нового рядка
  (CASE WHEN of.owner_username <> '' THEN '@' || of.owner_username ELSE '' END) ||
  (CASE WHEN of.owner_username <> '' THEN (CASE WHEN of.owner_username <> '' THEN ' / ' ELSE '' END) || of.owner_username ELSE '' END)
                                                                   AS admin_text,
  COALESCE(cno.names, cnd.names, '')                               AS duplicates_names, -- лише display name'и (без '@'), кожен з нового рядка
  ''                                                               AS notes,
  c.channel_id                                                     AS channel_id
FROM channels c
LEFT JOIN owner_final              of   ON of.channel_id = c.channel_id
LEFT JOIN links_agg                la   ON la.channel_id = c.channel_id
LEFT JOIN conflicts_names_official cno  ON cno.channel_id = c.channel_id
LEFT JOIN conflicts_names_derived  cnd  ON cnd.channel_id = c.channel_id
ORDER BY c.channel_id;
