#!/bin/bash

DB="post_watchdog.sqlite3"
OUT="schema_dump.txt"

# очистимо старий файл
echo "Dump schema for $DB" > "$OUT"
echo "====================" >> "$OUT"

tables=(
  channels
  channel_links
  invite_map
  invite_status
  invite_owners
  invite_check
  links
  username_map
  owner_conflicts
)

for t in "${tables[@]}"; do
  echo -e "\n=== .schema $t ===" >> "$OUT"
  sqlite3 "$DB" ".schema $t" >> "$OUT"

  echo -e "\n--- PRAGMA table_info($t) ---" >> "$OUT"
  sqlite3 "$DB" "PRAGMA table_info($t);" >> "$OUT"
done

echo -e "\nSchema dump saved to $OUT"