# Database Setup & Visualization Guide

> **Current state:** Postgres is running locally on `localhost:5432` with the `ffdraft` database populated. Two paths to visualize it:
>
> 1. **Supabase Studio** (web UI — full feature set)
> 2. **Postgres GUI client** (TablePlus, Postico, DBeaver — fastest)

---

## Option 1: Supabase Local (Recommended for Web UI)

Supabase wraps Postgres with a beautiful web interface (Studio) plus auth, real-time, and storage.

### Prerequisites
- Docker Desktop running
- Supabase CLI installed (`brew install supabase/tap/supabase`)

### Start Supabase

```bash
cd /path/to/Mew-
supabase start
```

After first-run image downloads, this exposes:

| Service | URL | Notes |
|---------|-----|-------|
| **Studio UI** | http://localhost:54323 | Browse tables, run SQL, view relationships |
| Postgres | `postgresql://postgres:postgres@localhost:54322/postgres` | Supabase's own Postgres instance |
| API | http://localhost:54321 | Auto-generated REST/GraphQL |

### Connect the `ffdraft` data to Supabase

Supabase local creates its **own** Postgres instance (port 54322). Your data is currently in the standalone Postgres on port 5432. You have two options:

**A) Migrate data into Supabase's Postgres**
```bash
# Dump your current ffdraft DB
pg_dump -h localhost -p 5432 -U dev1398 -d ffdraft > ffdraft_dump.sql

# Load it into Supabase's Postgres
psql -h localhost -p 54322 -U postgres -d postgres < ffdraft_dump.sql
```

**B) Just browse via a GUI client** (see Option 2) — much simpler if you only want to visualize.

### Stop Supabase
```bash
supabase stop
```

---

## Option 2: Postgres GUI Client (Fastest)

Connect any Postgres client directly to your existing local database.

### Connection settings

| Setting | Value |
|---------|-------|
| Host | `localhost` |
| Port | `5432` |
| Database | `ffdraft` |
| User | `dev1398` (or your macOS username) |
| Password | *(none required for local peer auth)* |

### Recommended clients

- **TablePlus** (macOS) — `brew install --cask tableplus`
- **Postico** (macOS) — `brew install --cask postico`
- **DBeaver** (cross-platform) — `brew install --cask dbeaver-community`
- **pgAdmin 4** — `brew install --cask pgadmin4`

---

## What's in the database right now

```sql
-- Quick overview
SELECT 'players' as table_name, count(*) FROM ff.player
UNION ALL SELECT 'aliases', count(*) FROM ff.player_alias
UNION ALL SELECT 'weekly_stats', count(*) FROM ff.player_week_stats
UNION ALL SELECT 'adp_snapshots', count(*) FROM ff.snapshot WHERE kind = 'adp'
UNION ALL SELECT 'adp_records', count(*) FROM ff.adp;
```

**Expected output:**
| table_name | count |
|------------|-------|
| players | ~7,963 |
| aliases | ~35,124 |
| weekly_stats | ~104,447 |
| adp_snapshots | 6 |
| adp_records | ~1,028 |

---

## Fun queries to run

### Top fantasy scorers by season
```sql
SELECT 
  p.full_name,
  w.season,
  SUM((w.stat_line->>'fantasy_points_ppr')::numeric) as total_ppr
FROM ff.player_week_stats w
JOIN ff.player p ON p.player_id = w.player_id
WHERE w.season_type = 'REG'
GROUP BY p.full_name, w.season
ORDER BY total_ppr DESC
LIMIT 20;
```

### ADP trends for a player across seasons
```sql
SELECT 
  s.season,
  p.full_name,
  a.adp
FROM ff.adp a
JOIN ff.snapshot s ON s.snapshot_id = a.snapshot_id
JOIN ff.player p ON p.player_id = a.player_id
WHERE p.full_name = 'Justin Jefferson'
ORDER BY s.season;
```

### Unresolved ADP records (should be 0 after filtering DEF/K)
```sql
SELECT s.season, COUNT(*) as unresolved
FROM ff.adp a
JOIN ff.snapshot s ON s.snapshot_id = a.snapshot_id
WHERE a.player_id IS NULL
GROUP BY s.season;
```
