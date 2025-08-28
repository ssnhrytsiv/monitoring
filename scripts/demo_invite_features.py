#!/usr/bin/env python3
"""
Demonstration script showing the new link normalization and negative caching features.

This script shows how the new system reduces API calls through:
1. Local format validation
2. URL normalization for better cache hits
3. Persistent negative caching
4. In-memory negative caching

Usage:
    python scripts/demo_invite_features.py
"""

import os
import sys
import tempfile

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.utils.link_parser import (
    normalize_url, extract_invite_hash, is_valid_invite_hash, 
    canonical_invite_url, is_invite, extract_links
)
from app.services.membership_db import (
    init, bad_invite_put, bad_invite_get, prune_bad_invites, url_put, url_get
)


def demo_url_normalization():
    """Demonstrate URL normalization features."""
    print("=" * 60)
    print("URL NORMALIZATION DEMO")
    print("=" * 60)
    
    test_urls = [
        "https://t.me/joinchat/ABCD1234567890abcd",
        "t.me/joinchat/EFGH1234567890efgh",
        "https://telegram.me/joinchat/IJKL1234567890ijkl?param=value",
        "t.me/+MNOP1234567890mnop",
        "https://t.me/+QRST1234567890qrst#fragment",
        "@username123",
        "https://telegram.me/channel456",
        "t.me/publicchannel",
        "(https://t.me/joinchat/UVWX1234567890uvwx)"
    ]
    
    print("Raw URL -> Normalized URL")
    print("-" * 60)
    for url in test_urls:
        normalized = normalize_url(url)
        print(f"{url}")
        print(f"  -> {normalized}")
        print()


def demo_invite_hash_validation():
    """Demonstrate local invite hash validation."""
    print("=" * 60)
    print("INVITE HASH VALIDATION DEMO")
    print("=" * 60)
    
    test_cases = [
        ("ABCD1234567890abcd", "Valid 18-char hash"),
        ("short", "Too short"),
        ("ABCD1234567890abcd1234567890", "Too long"),
        ("ABCD1234567890@bcd", "Invalid character (@)"),
        ("ABCD_1234-567890abcd", "Valid with underscore/dash"),
        ("", "Empty"),
        ("ABCD1234567890abcd!", "Invalid trailing character"),
    ]
    
    print("Hash -> Valid? (Reason)")
    print("-" * 60)
    for hash_val, description in test_cases:
        valid = is_valid_invite_hash(hash_val)
        print(f"{hash_val or '(empty)'} -> {valid} ({description})")


def demo_invite_extraction():
    """Demonstrate invite hash extraction from URLs."""
    print("=" * 60)
    print("INVITE HASH EXTRACTION DEMO")
    print("=" * 60)
    
    test_urls = [
        "https://t.me/joinchat/ABCD1234567890abcd",
        "t.me/+EFGH1234567890efgh",
        "https://t.me/joinchat/IJKL1234567890ijkl?param=value#fragment",
        "https://t.me/publicchannel",
        "@username"
    ]
    
    print("URL -> Extracted Hash -> Valid?")
    print("-" * 60)
    for url in test_urls:
        hash_val = extract_invite_hash(url)
        valid = is_valid_invite_hash(hash_val) if hash_val else False
        is_invite_link = is_invite(url)
        print(f"{url}")
        print(f"  Hash: '{hash_val}' | Valid: {valid} | Is invite: {is_invite_link}")
        print()


def demo_negative_caching():
    """Demonstrate persistent negative caching."""
    print("=" * 60)
    print("NEGATIVE CACHING DEMO")
    print("=" * 60)
    
    # Use temporary database
    with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as tmp:
        test_db = tmp.name
    
    try:
        # Initialize database
        init(test_db)
        print("Initialized temporary database")
        
        # Test bad invite caching
        test_hashes = [
            ("invalidhash123456789", "invalid"),
            ("privatehash987654321", "private"), 
            ("requestedhash456789123", "requested")
        ]
        
        print("\nCaching bad invite statuses...")
        for hash_val, status in test_hashes:
            bad_invite_put(hash_val, status)
            print(f"Cached: {hash_val} -> {status}")
        
        print("\nRetrieving cached statuses...")
        for hash_val, expected_status in test_hashes:
            cached_status = bad_invite_get(hash_val)
            print(f"Retrieved: {hash_val} -> {cached_status} (expected: {expected_status})")
        
        # Test non-existent hash
        non_existent = bad_invite_get("nonexistenthash")
        print(f"Non-existent hash: {non_existent}")
        
        # Test URL caching with normalization
        print("\nTesting URL cache with normalization...")
        test_url_pairs = [
            ("https://t.me/joinchat/ABCD1234567890abcd", "invalid"),
            ("t.me/joinchat/ABCD1234567890abcd", "should_hit_cache")  # Same normalized form
        ]
        
        # Cache first URL
        url_put(test_url_pairs[0][0], test_url_pairs[0][1])
        print(f"Cached: {test_url_pairs[0][0]} -> {test_url_pairs[0][1]}")
        
        # Try to retrieve with different format (should hit cache due to normalization)
        cached_status = url_get(test_url_pairs[1][0])
        print(f"Retrieved: {test_url_pairs[1][0]} -> {cached_status}")
        print(f"Cache hit due to normalization: {cached_status == test_url_pairs[0][1]}")
        
    finally:
        # Cleanup
        os.unlink(test_db)
        print(f"\nCleaned up temporary database: {test_db}")


def demo_link_extraction():
    """Demonstrate link extraction with normalization."""
    print("=" * 60)
    print("LINK EXTRACTION WITH NORMALIZATION DEMO")
    print("=" * 60)
    
    test_text = """
    Check out these channels:
    https://t.me/joinchat/ABCD1234567890abcd
    t.me/+EFGH1234567890efgh
    @username123
    https://telegram.me/publicchannel
    (t.me/joinchat/IJKL1234567890ijkl)
    Some duplicate: https://t.me/joinchat/ABCD1234567890abcd
    """
    
    print("Text content:")
    print(test_text.strip())
    print("\nExtracted and normalized links:")
    print("-" * 40)
    
    links = extract_links(test_text)
    for i, link in enumerate(links, 1):
        print(f"{i}. {link}")
    
    print(f"\nTotal unique normalized links: {len(links)}")


def main():
    """Run all demonstrations."""
    print("TELEGRAM LINK NORMALIZATION AND NEGATIVE CACHING")
    print("Feature Demonstration Script")
    print("\n" + "=" * 80)
    
    demos = [
        demo_url_normalization,
        demo_invite_hash_validation, 
        demo_invite_extraction,
        demo_link_extraction,
        demo_negative_caching
    ]
    
    for demo in demos:
        demo()
        print("\n")
    
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("✅ URL normalization: joinchat/HASH -> +hash, lowercase, strip fragments")
    print("✅ Local validation: Invalid hashes rejected without API calls")
    print("✅ Persistent negative cache: Bad invites cached across restarts")
    print("✅ URL cache normalization: Better cache hit rates")
    print("✅ Duplicate elimination: Normalized URLs deduplicated")
    print("\nThese features reduce Telegram API calls and FLOOD_WAIT incidents!")


if __name__ == "__main__":
    main()