"""CLI entrypoint for seed_creator.

Приклади:
  # випадковий мікс
  python -m app.services.feature.seed --count 10 --mix --target me

  # явний мікс приватних типів
  python -m app.services.feature.seed --private-open 3 --private-closed 2 --private-request 1 --target me

  # переслати останні N згенерованих лінків
  python -m app.services.feature.seed --resend-last 10 --target me
"""
import argparse
import asyncio
import logging
from typing import List, Dict

from app.services.feature import seed_db
from app.services.feature import seed_creator

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("seed_cli")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m app.services.feature.seed",
        description="Independent seed generator CLI (creates channels and sends invite links).",
    )
    # режим створення
    p.add_argument("--count", type=int, default=6, help="Total channels if no explicit mix is provided")
    p.add_argument("--mix", action="store_true", help="Random mix for kinds (public/private_open/private_closed/private_request)")
    p.add_argument("--public", type=int, default=0, help="Explicit public count")
    p.add_argument("--private-open", type=int, default=0, help="Explicit private_open count (instant join via invite)")
    p.add_argument("--private-closed", type=int, default=0, help="Explicit private_closed count (join request invite)")
    p.add_argument("--private-request", type=int, default=0, help="Explicit private_request count (join request invite)")
    p.add_argument("--title-prefix", type=str, default="SEED")

    # режим пересилки раніше створених
    p.add_argument("--resend-last", type=int, default=0, help="Resend last N invite links")

    # куди відсилати лінки
    p.add_argument("--target", type=str, default=None, help="Target peer (me, @username, chat id/link)")

    # розмір батчу при відправці
    p.add_argument("--send-batch", type=int, default=5, help="Batch size for sending links")
    return p


def _links_from_metas(metas: List[Dict]) -> List[str]:
    """Брати тільки invite_link; якщо його немає — пропускаємо елемент."""
    out: List[str] = []
    for m in metas:
        inv = m.get("invite_link")
        if inv:
            out.append(inv)
    return out


def _links_from_rows(rows: List[Dict]) -> List[str]:
    """Для resend беремо лише invite_link; без @username."""
    out: List[str] = []
    for r in rows:
        inv = r.get("invite_link")
        if inv:
            out.append(inv)
    return out


async def _resend_last(n: int, target: str, send_batch: int):
    seed_db.init()
    rows = seed_db.last_created(n)
    links = _links_from_rows(rows)
    if not links:
        print("nothing to resend")
        return

    B = max(1, int(send_batch))
    sent = 0
    for i in range(0, len(links), B):
        batch = links[i : i + B]
        await seed_creator.send_links(target or seed_creator.SEED_TARGET, batch)
        sent += len(batch)
        await asyncio.sleep(1.0)
    print(f"resent {sent} links to {target or seed_creator.SEED_TARGET}")


async def _run(args):
    seed_db.init()

    # Режим пересилки
    if args.resend_last and args.resend_last > 0:
        await _resend_last(args.resend_last, args.target, args.send_batch)
        return

    # Планування міксу
    explicit_mix = {}
    if args.public:
        explicit_mix["public"] = int(args.public)
    if args.private_open:
        explicit_mix["private_open"] = int(args.private_open)
    if args.private_closed:
        explicit_mix["private_closed"] = int(args.private_closed)
    if args.private_request:
        explicit_mix["private_request"] = int(args.private_request)

    if explicit_mix:
        total = sum(explicit_mix.values())
        log.info("seed_cli: creating explicit mix: %s (total=%d)", explicit_mix, total)
        metas = await seed_creator.create_batch(total, mix=explicit_mix, title_prefix=args.title_prefix)
    else:
        log.info("seed_cli: creating random mix count=%d (args.mix=%s)", args.count, bool(args.mix))
        metas = await seed_creator.create_batch(args.count, mix=None, title_prefix=args.title_prefix)

    links = _links_from_metas(metas)
    target = args.target or seed_creator.SEED_TARGET

    B = max(1, int(args.send_batch))
    sent = 0
    for i in range(0, len(links), B):
        batch = links[i : i + B]
        await seed_creator.send_links(target, batch)
        sent += len(batch)
        await asyncio.sleep(1.0)

    print(f"created {len(metas)} channels; sent {sent} links to {target}")


def main():
    parser = _build_parser()
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()