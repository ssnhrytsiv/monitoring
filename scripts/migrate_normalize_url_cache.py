#!/usr/bin/env python3
"""
One-off migration script to re-key existing url_cache entries into canonical normalized form
while preserving latest status timestamp.

This script updates existing URL cache entries to use the new normalized URL format,
which improves cache hit ratios and reduces redundant API calls.

Usage:
    python -m scripts.migrate_normalize_url_cache
"""

import os
import sqlite3
import sys
from typing import Dict, List, Tuple

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.utils.link_parser import normalize_url
from app.services.membership_db import DB_PATH


def migrate_url_cache():
    """
    Migrate existing url_cache entries to use normalized URLs.
    
    Strategy:
    1. Read all existing entries
    2. Group by normalized URL (keeping latest timestamp for conflicts)
    3. Replace all entries with normalized versions
    """
    
    print(f"Starting URL cache migration for database: {DB_PATH}")
    
    if not os.path.exists(DB_PATH):
        print(f"Database file not found: {DB_PATH}")
        return False
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA busy_timeout=3000;")
    
    try:
        # Read all existing entries
        cursor = conn.execute("SELECT url, status, ts FROM url_cache ORDER BY ts DESC")
        entries = cursor.fetchall()
        
        if not entries:
            print("No entries found in url_cache table")
            return True
        
        print(f"Found {len(entries)} existing URL cache entries")
        
        # Group by normalized URL, keeping latest timestamp
        normalized_entries: Dict[str, Tuple[str, int]] = {}  # normalized_url -> (status, ts)
        
        for url, status, ts in entries:
            try:
                normalized = normalize_url(url)
                if normalized and normalized != url:
                    # URL was changed by normalization
                    if normalized not in normalized_entries or ts > normalized_entries[normalized][1]:
                        normalized_entries[normalized] = (status, ts)
                    print(f"Normalizing: {url} -> {normalized}")
                else:
                    # URL was already normalized or empty
                    if url and (url not in normalized_entries or ts > normalized_entries[url][1]):
                        normalized_entries[url] = (status, ts)
            except Exception as e:
                print(f"Error normalizing URL '{url}': {e}")
                # Keep original URL on error
                if url and (url not in normalized_entries or ts > normalized_entries[url][1]):
                    normalized_entries[url] = (status, ts)
        
        print(f"After normalization: {len(normalized_entries)} unique entries")
        
        # Backup original table
        print("Creating backup table...")
        conn.execute("CREATE TABLE IF NOT EXISTS url_cache_backup AS SELECT * FROM url_cache")
        backup_count = conn.execute("SELECT COUNT(*) FROM url_cache_backup").fetchone()[0]
        print(f"Backed up {backup_count} entries to url_cache_backup table")
        
        # Clear original table
        conn.execute("DELETE FROM url_cache")
        
        # Insert normalized entries
        print("Inserting normalized entries...")
        for normalized_url, (status, ts) in normalized_entries.items():
            conn.execute(
                "INSERT INTO url_cache (url, status, ts) VALUES (?, ?, ?)",
                (normalized_url, status, ts)
            )
        
        # Commit changes
        conn.commit()
        
        # Verify results
        final_count = conn.execute("SELECT COUNT(*) FROM url_cache").fetchone()[0]
        print(f"Migration completed successfully!")
        print(f"Original entries: {len(entries)}")
        print(f"Final entries: {final_count}")
        print(f"Entries saved: {len(entries) - final_count}")
        
        # Show some examples
        print("\nExample normalized URLs:")
        sample_cursor = conn.execute("SELECT url FROM url_cache LIMIT 5")
        for (url,) in sample_cursor.fetchall():
            print(f"  {url}")
        
        return True
        
    except Exception as e:
        print(f"Migration failed: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


def cleanup_backup():
    """Remove backup table after successful migration."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("DROP TABLE IF EXISTS url_cache_backup")
        conn.commit()
        print("Backup table removed")
    except Exception as e:
        print(f"Error removing backup table: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    print("URL Cache Migration Script")
    print("=" * 40)
    
    success = migrate_url_cache()
    
    if success:
        response = input("\nMigration completed successfully. Remove backup table? (y/N): ")
        if response.lower() == 'y':
            cleanup_backup()
        else:
            print("Backup table preserved as 'url_cache_backup'")
    else:
        print("Migration failed. Database unchanged.")
        sys.exit(1)