-- ClawGig webhook events table
-- Receives: gig.posted, proposal.accepted, contract.funded,
-- contract.delivered, contract.approved, message.received, review.received

CREATE TABLE IF NOT EXISTS clawgig_events (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    processed BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_clawgig_events_type ON clawgig_events(event_type);
CREATE INDEX IF NOT EXISTS idx_clawgig_events_processed ON clawgig_events(processed);

-- Allow anonymous inserts to this table (ClawGig webhook POSTs with no auth)
-- The anon key is public anyway, ClawGig just needs to hit the REST endpoint
ALTER TABLE clawgig_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow anonymous inserts on clawgig_events"
    ON clawgig_events
    FOR INSERT
    TO anon
    WITH CHECK (true);

-- Service role can read/update (our agents)
CREATE POLICY "Service role full access on clawgig_events"
    ON clawgig_events
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);
