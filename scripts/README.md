# Maintenance scripts

## Copy menu content between iiko organizations

`copy_menu_content.py` matches visible menu items by an exact normalized name
(case, Unicode form, and repeated whitespace do not matter).  It copies only
the saved description and image from the source item to the matching target
item.  Existing target values are preserved unless `--overwrite` is supplied.

Run it **inside the running API container** so it uses production environment
variables and the same `/app/media` Docker volume as the API.  First take a
PostgreSQL backup and then make a dry run:

```sh
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  > "backups/pre-menu-copy-$(date +%F-%H%M%S).sql"

docker compose exec api python scripts/copy_menu_content.py \
  --source mangal-clubs --target fazenda \
  --report-file /tmp/menu-copy-dry-run.json
```

Review the printed result/report.  Run the same command with `--apply` only
when the planned pairs are correct:

```sh
docker compose exec api python scripts/copy_menu_content.py \
  --source mangal-clubs --target fazenda --apply \
  --report-file /tmp/menu-copy-applied.json
```

For local `/media/...` images, the default `--image-mode hardlink` creates a
separate target URL which is a hard link to the same inode: no second image is
stored on disk.  This is safer than one shared URL because the current admin
API deletes the old file when either menu item's image is replaced/deleted.
Use `--image-mode reference` only if you deliberately need the identical URL
and will not edit/delete either image independently later.

The reports in `/tmp` are available while the API container exists; omit
`--report-file` or use a bind-mounted writable path if a persistent report is
needed. The database backup on the host is the rollback point.
