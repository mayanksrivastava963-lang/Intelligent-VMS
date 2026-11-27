# Backup & Restore Guide

## Overview

Intelligent-VMS stores data in three locations that require backup:

1. **PostgreSQL database** — camera configuration, user accounts, recording metadata, audit logs
2. **Recording storage volume** — the actual video segment files
3. **Configuration files** — `.env.production`, TLS certificates

## Automated Backup

Run the included backup script:

```powershell
.\scripts\backup_restore.ps1 -Action backup
```

This creates a timestamped backup in `backups/` containing:
- `database.sql` — full PostgreSQL dump
- `.env.production` — deployment configuration
- `tls/` — TLS certificates
- `backup-manifest.json` — backup metadata

## Manual PostgreSQL Backup

```bash
# From the host
docker exec intelligent-vms-postgres-1 pg_dumpall -U postgres > backup.sql

# Compressed
docker exec intelligent-vms-postgres-1 pg_dumpall -U postgres | gzip > backup.sql.gz
```

## Recording Volume Backup

The recording storage volume contains all video segments. For large deployments:

```bash
# Identify the volume
docker volume inspect intelligent-vms-recordings

# Backup to external storage
docker run --rm -v intelligent-vms-recordings:/data -v /backup:/backup alpine \
  tar czf /backup/recordings-$(date +%Y%m%d).tar.gz -C /data .
```

> **Note:** Recording volumes can be very large (100GB+). Consider incremental backup solutions like rsync for production deployments.

## Restore

### From Backup Script

```powershell
.\scripts\backup_restore.ps1 -Action restore -BackupPath .\backups\vms-backup-20261127-120000
```

### Manual Database Restore

```bash
# Stop the application first
docker compose -f compose.production.yml down

# Restore database
cat backup.sql | docker exec -i intelligent-vms-postgres-1 psql -U postgres

# Restart
docker compose -f compose.production.yml up -d
```

## Backup Schedule Recommendations

| Deployment Size | Database | Recordings | Configuration |
|---|---|---|---|
| Small (1-10 cameras) | Daily | Weekly | On change |
| Medium (10-30 cameras) | Every 6 hours | Daily | On change |
| Enterprise (30-60+ cameras) | Hourly | Continuous rsync | On change |

## Disaster Recovery

1. Install Docker and Docker Compose on the new server
2. Copy the backup archive to the new server
3. Run `scripts/setup.ps1` to generate new `.env.production` (or restore the backed-up one)
4. Restore the database from backup
5. Restore TLS certificates
6. Start the stack: `scripts/start.ps1`
7. Verify: `scripts/status.ps1`
