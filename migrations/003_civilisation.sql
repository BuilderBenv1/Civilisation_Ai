-- Agent Town Civilisation Schema — Phase 1-3 infrastructure
-- Run against Supabase SQL editor

-- ── PHASE 1: THE VILLAGE ────────────────────────────────────────────

-- Every agent ever spawned — lineage tracking
CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    agent_type TEXT NOT NULL,                    -- scout, worker, bd, darwin
    parent_agent UUID REFERENCES agents(id),     -- NULL for founders
    generation INT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',        -- active, terminated, quarantined
    spawned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    terminated_at TIMESTAMPTZ,
    total_earned NUMERIC(12,2) NOT NULL DEFAULT 0,
    tasks_completed INT NOT NULL DEFAULT 0,
    evolutions_applied INT NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

-- Seed the founding generation
INSERT INTO agents (name, agent_type, generation, status) VALUES
    ('Scout', 'scout', 0, 'active'),
    ('Worker', 'worker', 0, 'active'),
    ('BD', 'bd', 0, 'active'),
    ('Darwin', 'darwin', 0, 'active')
ON CONFLICT DO NOTHING;

-- Evolution proposals — Darwin's change requests
CREATE TABLE IF NOT EXISTS proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposed_by TEXT NOT NULL DEFAULT 'darwin',   -- agent name
    target_agent TEXT NOT NULL,                   -- which agent to change
    change_type TEXT NOT NULL,                    -- code_change, config, new_skill, new_crawler
    change_description TEXT NOT NULL,
    code_diff TEXT,                               -- the actual diff or new code
    target_file TEXT,                             -- file path being modified
    fitness_score NUMERIC(4,3),                   -- 0.000 - 1.000
    applied BOOLEAN NOT NULL DEFAULT false,
    outcome_delta JSONB,                         -- measured impact after applying
    rollback_hash TEXT,                           -- git commit to revert to
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied_at TIMESTAMPTZ,
    reverted_at TIMESTAMPTZ
);

-- Evolution log — every change Darwin has made
CREATE TABLE IF NOT EXISTS evolution_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name TEXT NOT NULL,
    change_type TEXT NOT NULL,
    proposal_id UUID REFERENCES proposals(id),
    description TEXT NOT NULL,
    fitness_score NUMERIC(4,3),
    applied BOOLEAN NOT NULL DEFAULT false,
    outcome_delta JSONB,
    git_commit TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── PHASE 2: THE TOWN (schema ready, activates at $500) ────────────

CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    purpose TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'dormant',       -- dormant, active, dissolved
    founded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    founding_agents JSONB DEFAULT '[]',
    treasury_allocation NUMERIC(12,2) NOT NULL DEFAULT 0,
    revenue_split JSONB DEFAULT '{"town": 0.7, "company": 0.3}',
    total_revenue NUMERIC(12,2) NOT NULL DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

-- ── PHASE 3: THE CITY (schema ready, activates at $5,000) ──────────

CREATE TABLE IF NOT EXISTS council_seats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    seat_name TEXT NOT NULL UNIQUE,               -- treasury, security, growth, evolution, diplomacy
    held_by TEXT,                                  -- agent name
    performance_score NUMERIC(6,4) DEFAULT 0,
    appointed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Seed council seats (empty until Phase 3 activates)
INSERT INTO council_seats (seat_name) VALUES
    ('treasury'), ('security'), ('growth'), ('evolution'), ('diplomacy')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS council_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_type TEXT NOT NULL,
    description TEXT NOT NULL,
    votes JSONB NOT NULL DEFAULT '{}',            -- {seat_name: vote, ...}
    outcome TEXT NOT NULL,                         -- approved, rejected, vetoed
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB DEFAULT '{}'
);

-- Security events — threat log
CREATE TABLE IF NOT EXISTS security_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,                     -- injection, anomaly, drift, quarantine
    severity TEXT NOT NULL DEFAULT 'medium',      -- low, medium, high, critical
    agent_name TEXT,
    description TEXT NOT NULL,
    resolved BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type);
CREATE INDEX IF NOT EXISTS idx_proposals_applied ON proposals(applied);
CREATE INDEX IF NOT EXISTS idx_proposals_target ON proposals(target_agent);
CREATE INDEX IF NOT EXISTS idx_evolution_log_agent ON evolution_log(agent_name);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);
CREATE INDEX IF NOT EXISTS idx_security_events_resolved ON security_events(resolved);
CREATE INDEX IF NOT EXISTS idx_council_decisions_date ON council_decisions(decided_at DESC);
