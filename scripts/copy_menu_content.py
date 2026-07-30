"""Copy menu descriptions and images between two iiko organizations.

The application stores menu content globally, keyed by iiko item id/SKU, while
each organization has its own iiko menu snapshot.  This utility matches the
items in two snapshots by normalized *exact* name and creates/updates only the
target keys.

It never uploads images.  For local ``/media/...`` images the default is to
create a filesystem hard link in ``MEDIA_ROOT``.  A hard link is a second path
to the same file data, so it does not consume another copy of the image and is
safe if one menu item is subsequently edited or deleted by the admin API.

Run without --apply first.  All database changes are one transaction; a failed
operation rolls it back.  The script intentionally never deletes media files.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402
from app.db.session import AsyncSessionLocal, engine  # noqa: E402
from app.models.menu import IikoMenuSnapshot, MenuItemContent  # noqa: E402
from app.models.organization import Organization  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Copy menu descriptions and images by exact normalized iiko item name."
    )
    parser.add_argument("--source", required=True, help="Source organization slug, e.g. mangal-clubs")
    parser.add_argument("--target", required=True, help="Target organization slug, e.g. fazenda")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes. The default is a read-only dry run.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace non-empty target description/image values. Default: preserve them.",
    )
    parser.add_argument(
        "--image-mode",
        choices=("hardlink", "reference"),
        default="hardlink",
        help=(
            "For local /media images: hardlink (default, same disk bytes but independent path) "
            "or reference (store precisely the source URL; unsafe if either item is later edited/deleted)."
        ),
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=None,
        help="Write the dry-run/apply plan, including old target values, as JSON.",
    )
    return parser.parse_args()


def normalize_name(value: Any) -> str:
    """Normalize harmless formatting differences; never perform fuzzy matching."""
    if value is None:
        return ""
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return re.sub(r"\s+", " ", value).strip()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def menu_items(snapshot: IikoMenuSnapshot) -> list[dict[str, str | None]]:
    """Flatten non-hidden iiko items, retaining the keys used by the API."""
    raw_menu = snapshot.raw_menu or {}
    result: list[dict[str, str | None]] = []
    seen: set[str] = set()

    for category in raw_menu.get("itemCategories") or []:
        if not isinstance(category, dict) or category.get("isHidden") or category.get("isDeleted"):
            continue
        for item in category.get("items") or []:
            if not isinstance(item, dict) or item.get("isHidden") or item.get("isDeleted"):
                continue

            item_id = optional_text(item.get("itemId") or item.get("id"))
            sku = optional_text(item.get("sku"))
            name = optional_text(item.get("name"))
            key = item_id or sku or normalize_name(name)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append({"id": item_id, "sku": sku, "name": name})

    return result


def index_items(items: list[dict[str, str | None]]) -> dict[str, list[dict[str, str | None]]]:
    index: dict[str, list[dict[str, str | None]]] = {}
    for item in items:
        name = normalize_name(item.get("name"))
        if name:
            index.setdefault(name, []).append(item)
    return index


def content_candidates(
    contents: list[MenuItemContent], *, item_id: str | None, sku: str | None
) -> list[MenuItemContent]:
    found = {
        content.id: content
        for content in contents
        if (item_id and content.iiko_item_id == item_id) or (sku and content.sku == sku)
    }
    return list(found.values())


def content_values(content: MenuItemContent | None) -> dict[str, Any]:
    if content is None:
        return {"id": None, "iiko_item_id": None, "sku": None, "description": None, "image_url": None}
    return {
        "id": str(content.id),
        "iiko_item_id": content.iiko_item_id,
        "sku": content.sku,
        "description": content.description,
        "image_url": content.image_url,
    }


def local_media_path(image_url: str) -> Path | None:
    """Return an existing local media file only for URLs under MEDIA_URL."""
    media_url = settings.media_url.rstrip("/")
    prefix = f"{media_url}/"
    if not image_url.startswith(prefix):
        return None

    media_root = Path(settings.media_root).resolve()
    candidate = (media_root / image_url.removeprefix(prefix)).resolve()
    if media_root not in candidate.parents or not candidate.is_file():
        return None
    return candidate


def hardlink_url(*, source_url: str, target_content_id: uuid.UUID) -> tuple[str, Path] | None:
    """Build a target-owned URL for a hard link to a local source image."""
    source_path = local_media_path(source_url)
    if source_path is None:
        return None

    suffix = source_path.suffix.lower()
    if not suffix:
        suffix = ".img"
    media_root = Path(settings.media_root).resolve()
    destination = media_root / "menu" / f"{target_content_id}-linked{suffix}"
    return f"{settings.media_url.rstrip('/')}/menu/{destination.name}", destination


def serialize_plan(plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop runtime-only Path objects before writing the JSON report."""
    return [{key: value for key, value in operation.items() if key != "hardlink"} for operation in plan]


def print_plan(plan: list[dict[str, Any]], *, apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"[{mode}] planned database operations: {len(plan)}")
    for operation in plan:
        fields = ", ".join(operation["fields"])
        link_note = " + hardlink" if operation.get("hardlink") else ""
        print(f"{operation['action']}: {operation['name']!r} -> {fields}{link_note}")


async def copy_content(args: argparse.Namespace) -> int:
    source_slug = args.source.strip().lower()
    target_slug = args.target.strip().lower()
    if not source_slug or not target_slug or source_slug == target_slug:
        print("--source and --target must be different non-empty organization slugs.", file=sys.stderr)
        return 2

    async with AsyncSessionLocal() as db:
        organizations = list(
            await db.scalars(select(Organization).where(Organization.slug.in_((source_slug, target_slug))))
        )
        organizations_by_slug = {organization.slug: organization for organization in organizations}
        source_org = organizations_by_slug.get(source_slug)
        target_org = organizations_by_slug.get(target_slug)
        if not source_org or not target_org:
            print(f"Organization not found: {args.source if not source_org else args.target}", file=sys.stderr)
            return 2

        snapshots = {
            snapshot.organization_id: snapshot
            for snapshot in await db.scalars(
                select(IikoMenuSnapshot).where(
                    IikoMenuSnapshot.organization_id.in_((source_org.id, target_org.id))
                )
            )
        }
        source_snapshot = snapshots.get(source_org.id)
        target_snapshot = snapshots.get(target_org.id)
        if not source_snapshot or not source_snapshot.raw_menu:
            print(f"Source organization has no iiko menu snapshot: {source_org.slug}", file=sys.stderr)
            return 2
        if not target_snapshot or not target_snapshot.raw_menu:
            print(f"Target organization has no iiko menu snapshot: {target_org.slug}", file=sys.stderr)
            return 2

        contents = list(await db.scalars(select(MenuItemContent)))
        source_index = index_items(menu_items(source_snapshot))
        plan: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        warnings: list[dict[str, str]] = []

        for target_item in menu_items(target_snapshot):
            name = optional_text(target_item.get("name")) or ""
            source_matches = source_index.get(normalize_name(name), [])
            if len(source_matches) != 1:
                reason = "source name not found" if not source_matches else "ambiguous source name"
                skipped.append({"name": name, "reason": reason})
                continue

            source_item = source_matches[0]
            source_rows = content_candidates(contents, item_id=source_item["id"], sku=source_item["sku"])
            if len(source_rows) > 1:
                skipped.append({"name": name, "reason": "source id and SKU point to different content rows"})
                continue
            source_content = source_rows[0] if source_rows else None
            source_description = optional_text(source_content.description if source_content else None)
            source_image = optional_text(source_content.image_url if source_content else None)
            if not source_description and not source_image:
                skipped.append({"name": name, "reason": "source has no saved description or image"})
                continue

            if not target_item["id"] and not target_item["sku"]:
                skipped.append({"name": name, "reason": "target item has no iiko id or SKU"})
                continue
            target_rows = content_candidates(contents, item_id=target_item["id"], sku=target_item["sku"])
            if len(target_rows) > 1:
                skipped.append({"name": name, "reason": "target id and SKU point to different content rows"})
                continue
            target_content = target_rows[0] if target_rows else None
            if target_content is source_content:
                # Same SKU/id already resolves to the source's global content row.
                continue

            target_id = target_content.id if target_content else uuid.uuid4()
            target_description = optional_text(target_content.description if target_content else None)
            target_image = optional_text(target_content.image_url if target_content else None)
            fields: list[str] = []
            after_image = target_image
            link: dict[str, str] | None = None

            if source_description and (args.overwrite or not target_description) and source_description != target_description:
                fields.append("description")

            if source_image and (args.overwrite or not target_image):
                if args.image_mode == "hardlink":
                    link_result = hardlink_url(source_url=source_image, target_content_id=target_id)
                    if link_result:
                        link_url, link_path = link_result
                        if link_url != target_image:
                            fields.append("image_url")
                            after_image = link_url
                            link = {"source": source_image, "destination": str(link_path)}
                    else:
                        # External URLs have no local file to link; referencing them is safe.
                        if source_image.startswith(f"{settings.media_url.rstrip('/')}/"):
                            warnings.append({"name": name, "reason": f"local source image is missing: {source_image}"})
                        elif source_image != target_image:
                            fields.append("image_url")
                            after_image = source_image
                elif source_image != target_image:
                    fields.append("image_url")
                    after_image = source_image

            if not fields:
                continue

            before = content_values(target_content)
            after = dict(before)
            after.update(
                {
                    "id": str(target_id),
                    "iiko_item_id": target_item["id"],
                    "sku": target_item["sku"],
                    "description": source_description if "description" in fields else target_description,
                    "image_url": after_image,
                }
            )
            plan.append(
                {
                    "action": "create" if target_content is None else "update",
                    "name": name,
                    "fields": fields,
                    "source": content_values(source_content),
                    "target": {"id": str(target_id), "iiko_item_id": target_item["id"], "sku": target_item["sku"]},
                    "before": before,
                    "after": after,
                    "hardlink": link,
                }
            )

        print_plan(plan, apply=args.apply)
        print(f"Skipped: {len(skipped)}; warnings: {len(warnings)}")
        for item in skipped:
            print(f"skip: {item['name']!r} ({item['reason']})")
        for item in warnings:
            print(f"warning: {item['name']!r} ({item['reason']})")

        report = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source_org.slug,
            "target": target_org.slug,
            "apply": args.apply,
            "overwrite": args.overwrite,
            "image_mode": args.image_mode,
            "operations": serialize_plan(plan),
            "skipped": skipped,
            "warnings": warnings,
        }
        if args.report_file:
            args.report_file.parent.mkdir(parents=True, exist_ok=True)
            args.report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Report written: {args.report_file}")

        if not args.apply or not plan:
            return 0

        created_links: list[Path] = []
        try:
            for operation in plan:
                link = operation["hardlink"]
                if not link:
                    continue
                source_path = Path(link["source"])
                # Re-resolve from URL at apply time in case the file disappeared after the dry run.
                source_path = local_media_path(link["source"])
                destination = Path(link["destination"])
                if source_path is None:
                    raise RuntimeError(f"Source image disappeared before apply: {link['source']}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if not destination.samefile(source_path):
                        raise RuntimeError(f"Refusing to overwrite existing media file: {destination}")
                else:
                    os.link(source_path, destination)
                    created_links.append(destination)

            for operation in plan:
                target = operation["target"]
                target_rows = content_candidates(contents, item_id=target["iiko_item_id"], sku=target["sku"])
                target_content = target_rows[0] if target_rows else None
                after = operation["after"]
                if target_content is None:
                    target_content = MenuItemContent(
                        id=uuid.UUID(after["id"]),
                        iiko_item_id=after["iiko_item_id"],
                        sku=after["sku"],
                        description=after["description"],
                        image_url=after["image_url"],
                    )
                    db.add(target_content)
                    contents.append(target_content)
                else:
                    target_content.description = after["description"]
                    target_content.image_url = after["image_url"]
            await db.commit()
        except (OSError, RuntimeError, IntegrityError, SQLAlchemyError) as exc:
            await db.rollback()
            for path in reversed(created_links):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    print(f"Could not remove rollback hard link: {path}", file=sys.stderr)
            print(f"No database changes committed: {exc}", file=sys.stderr)
            return 1

        print(f"Committed: {len(plan)} operation(s). No image was uploaded, copied, or deleted.")
        return 0


async def async_main() -> int:
    try:
        return await copy_content(parse_args())
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(async_main()))
