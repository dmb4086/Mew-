-- Phase 0 — Data spine: snapshot tables + player identity.
--
-- Design rule: everything that changes over time is stored as a time-stamped
-- snapshot so we can reconstruct exactly what the system believed AT DRAFT TIME,
-- not after the season. We never UPDATE a projection/ADP row in place; we insert
-- a new snapshot.
--
-- Target: Postgres / Supabase. Safe to run repeatedly (IF NOT EXISTS).

create schema if not exists ff;

-- ---------------------------------------------------------------------------
-- Canonical player identity
-- ---------------------------------------------------------------------------
-- One row per real human football player. External IDs from each source map
-- INTO this canonical id via player_alias. This is the spine of Phase 0.
create table if not exists ff.player (
    player_id      bigint generated always as identity primary key,
    full_name      text        not null,
    first_name     text,
    last_name      text,
    position       text,                       -- QB/RB/WR/TE/K/DST
    team           text,                       -- current NFL team abbrev
    birthdate      date,
    -- Stable cross-source keys when available (nflverse is our backbone):
    gsis_id        text,                        -- nflverse / NFL GSIS
    created_at     timestamptz not null default now(),
    updated_at     timestamptz not null default now()
);
create unique index if not exists player_gsis_uidx
    on ff.player (gsis_id) where gsis_id is not null;
create index if not exists player_name_pos_idx
    on ff.player (lower(full_name), position);

-- External-source id -> canonical player_id. The resolver writes here.
create table if not exists ff.player_alias (
    alias_id    bigint generated always as identity primary key,
    player_id   bigint not null references ff.player(player_id) on delete cascade,
    source      text   not null,    -- 'sleeper' | 'nflverse' | 'adp:<provider>' | 'espn' | 'yahoo' | 'pfr'
    source_id   text   not null,    -- the id as that source knows it
    source_name text,               -- the name as that source spells it (for audit)
    confidence  real   not null default 1.0,  -- 1.0 = exact key match, <1 = fuzzy
    method      text,               -- how the match was made (gsis|exact|fuzzy|manual)
    created_at  timestamptz not null default now(),
    unique (source, source_id)
);
create index if not exists player_alias_player_idx on ff.player_alias (player_id);

-- ---------------------------------------------------------------------------
-- Snapshots: anything time-varying lands here, append-only.
-- ---------------------------------------------------------------------------
-- A snapshot groups a batch of rows captured at one instant from one source.
create table if not exists ff.snapshot (
    snapshot_id  bigint generated always as identity primary key,
    kind         text not null,      -- 'adp' | 'projection' | 'depth_chart' | 'injury' | 'sleeper_players'
    source       text not null,      -- provider/system the data came from
    season       int,                -- NFL season the data describes
    week         int,                -- null = preseason/season-long
    captured_at  timestamptz not null default now(),
    notes        text
);
create index if not exists snapshot_kind_season_idx on ff.snapshot (kind, season, captured_at);

create table if not exists ff.adp (
    snapshot_id bigint not null references ff.snapshot(snapshot_id) on delete cascade,
    player_id   bigint references ff.player(player_id),
    source_id   text,               -- raw id before/if resolution fails
    adp         numeric not null,   -- average draft position
    adp_rank    int,                -- positional or overall rank if provided
    sample_size int
);
create unique index if not exists adp_pk_idx
    on ff.adp (snapshot_id, coalesce(player_id, -1), coalesce(source_id, ''));

create table if not exists ff.projection (
    snapshot_id bigint not null references ff.snapshot(snapshot_id) on delete cascade,
    player_id   bigint references ff.player(player_id),
    source_id   text,
    -- Store raw projected stat lines (json) so any league's scoring engine can
    -- recompute fantasy points. Optionally cache a fantasy_points for one format.
    stat_line   jsonb not null default '{}'::jsonb,
    fantasy_points numeric,
    scoring_format text            -- describes fantasy_points if cached
);
create unique index if not exists projection_pk_idx
    on ff.projection (snapshot_id, coalesce(player_id, -1), coalesce(source_id, ''));

create table if not exists ff.depth_chart (
    snapshot_id bigint not null references ff.snapshot(snapshot_id) on delete cascade,
    player_id   bigint references ff.player(player_id),
    team        text not null,
    position    text not null,
    depth_order int                -- 1 = starter
);
create unique index if not exists depth_chart_pk_idx
    on ff.depth_chart (snapshot_id, coalesce(player_id, -1), team, position);

create table if not exists ff.injury (
    snapshot_id bigint not null references ff.snapshot(snapshot_id) on delete cascade,
    player_id   bigint references ff.player(player_id),
    status      text,               -- Out/Doubtful/Questionable/IR/...
    detail      text
);
create unique index if not exists injury_pk_idx
    on ff.injury (snapshot_id, coalesce(player_id, -1));

-- ---------------------------------------------------------------------------
-- Historical truth: actual weekly stats (for backtesting & scoring gate).
-- ---------------------------------------------------------------------------
create table if not exists ff.player_week_stats (
    player_id   bigint not null references ff.player(player_id),
    season      int    not null,
    week        int    not null,
    team        text,
    opponent    text,
    stat_line   jsonb  not null default '{}'::jsonb,  -- raw counting stats
    source      text   not null default 'nflverse',
    loaded_at   timestamptz not null default now(),
    primary key (player_id, season, week, source)
);
create index if not exists pws_season_week_idx on ff.player_week_stats (season, week);

-- ---------------------------------------------------------------------------
-- Leagues & drafts (Sleeper to start)
-- ---------------------------------------------------------------------------
create table if not exists ff.league (
    league_id   text primary key,           -- platform league id
    platform    text not null,              -- 'sleeper' | 'espn' | 'yahoo'
    season      int,
    name        text,
    settings    jsonb not null default '{}'::jsonb,   -- raw platform settings
    scoring     jsonb not null default '{}'::jsonb,   -- raw scoring settings
    roster_positions text[],                -- e.g. {QB,RB,RB,WR,WR,TE,FLEX,...}
    created_at  timestamptz not null default now()
);

create table if not exists ff.draft (
    draft_id    text primary key,
    league_id   text references ff.league(league_id),
    platform    text not null,
    season      int,
    draft_type  text,                       -- snake/auction/linear
    status      text,                       -- pre_draft/drafting/complete
    settings    jsonb not null default '{}'::jsonb,
    slot_to_roster jsonb,                   -- draft slot -> roster mapping
    started_at  timestamptz,
    created_at  timestamptz not null default now()
);

create table if not exists ff.draft_pick (
    draft_id    text not null references ff.draft(draft_id) on delete cascade,
    pick_no     int  not null,              -- overall pick number
    round       int,
    draft_slot  int,                        -- which seat made the pick
    roster_id   int,
    picked_by   text,                       -- platform user id (the manager)
    player_id   bigint references ff.player(player_id),
    source_player_id text,                  -- raw platform player id
    picked_at   timestamptz,
    primary key (draft_id, pick_no)
);
create index if not exists draft_pick_user_idx on ff.draft_pick (picked_by);

-- Managers (for the Zev model in Phase 6)
create table if not exists ff.manager (
    user_id     text primary key,           -- platform user id
    platform    text not null,
    username    text,
    display_name text,
    notes       text
);
