-- Agent Town: Supabase Schema
-- Run this against your Supabase project via the SQL editor

-- Opportunities board (Scout -> Worker)
CREATE TABLE IF NOT EXISTS opportunities (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    platform TEXT NOT NULL,
    task_description TEXT NOT NULL,
    estimated_value NUMERIC(12, 2),
    currency TEXT DEFAULT 'USD',
    complexity TEXT CHECK (complexity IN ('low', 'medium', 'high')),
    source_url TEXT,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    status TEXT DEFAULT 'new' CHECK (status IN ('new', 'assigned', 'in_progress', 'completed', 'failed')),
    assigned_to TEXT,
    failure_reason TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Treasury (all agent income)
CREATE TABLE IF NOT EXISTS treasury (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    source_agent TEXT NOT NULL CHECK (source_agent IN ('scout', 'worker', 'bd')),
    source_platform TEXT NOT NULL,
    amount NUMERIC(18, 8) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    tx_hash TEXT,
    received_at TIMESTAMPTZ DEFAULT NOW(),
    task_id UUID REFERENCES opportunities(id),
    metadata JSONB DEFAULT '{}'::jsonb
);

-- BD prospects (CRM)
CREATE TABLE IF NOT EXISTS prospects (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    handle TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'twitter',
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    context TEXT,
    deal_stage TEXT DEFAULT 'new' CHECK (deal_stage IN ('new', 'contacted', 'warm', 'converted', 'dead')),
    last_contact TIMESTAMPTZ,
    notes TEXT,
    outreach_history JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_prospects_handle_platform UNIQUE (handle, platform)
);

-- Outreach log (BD approval queue)
CREATE TABLE IF NOT EXISTS outreach_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    prospect_id UUID REFERENCES prospects(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'twitter_dm',
    message_draft TEXT NOT NULL,
    approved BOOLEAN DEFAULT FALSE,
    sent_at TIMESTAMPTZ,
    response TEXT,
    outcome TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Agent messages (inter-agent comms)
CREATE TABLE IF NOT EXISTS agent_messages (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    from_agent TEXT NOT NULL CHECK (from_agent IN ('scout', 'worker', 'bd', 'system')),
    to_agent TEXT NOT NULL CHECK (to_agent IN ('scout', 'worker', 'bd', 'system', 'all')),
    message_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    read BOOLEAN DEFAULT FALSE
);

-- Agent run log (tracks every execution cycle)
CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_name TEXT NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    summary JSONB DEFAULT '{}'::jsonb,
    error TEXT
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_opportunities_status ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_discovered ON opportunities(discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_treasury_received ON treasury(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_treasury_agent ON treasury(source_agent);
CREATE INDEX IF NOT EXISTS idx_prospects_stage ON prospects(deal_stage);
CREATE INDEX IF NOT EXISTS idx_outreach_approved ON outreach_log(approved);
CREATE INDEX IF NOT EXISTS idx_agent_messages_to ON agent_messages(to_agent, read);
CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent_name, started_at DESC);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_opportunities_updated
    BEFORE UPDATE ON opportunities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_prospects_updated
    BEFORE UPDATE ON prospects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
