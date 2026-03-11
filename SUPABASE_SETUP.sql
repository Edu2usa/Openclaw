-- ══════════════════════════════════════════════════════════════
-- Preferred Maintenance – Equipment Tracker
-- Run this in: Supabase Dashboard → SQL Editor → New Query
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS accounts (
    id           SERIAL PRIMARY KEY,
    account_name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('client', 'warehouse', 'spare_pool')),
    location     TEXT NOT NULL,
    active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS equipment_items (
    id                SERIAL PRIMARY KEY,
    name              TEXT NOT NULL,
    equipment_type    TEXT NOT NULL,
    account_id        INTEGER NOT NULL REFERENCES accounts(id) ON DELETE RESTRICT,
    quantity          INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    item_status       TEXT NOT NULL DEFAULT 'working'
                        CHECK (item_status IN ('working', 'in_repair', 'in_storage')),
    last_service_date DATE,
    created_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS equipment_repairs (
    id               SERIAL PRIMARY KEY,
    equipment_id     INTEGER NOT NULL REFERENCES equipment_items(id) ON DELETE CASCADE,
    maintenance_type TEXT NOT NULL,
    service_date     DATE NOT NULL,
    notes            TEXT,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Allow anon key full access (disable RLS)
ALTER TABLE accounts         DISABLE ROW LEVEL SECURITY;
ALTER TABLE equipment_items  DISABLE ROW LEVEL SECURITY;
ALTER TABLE equipment_repairs DISABLE ROW LEVEL SECURITY;
