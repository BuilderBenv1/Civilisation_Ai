# Agent Town

Three autonomous agents running 24/7, generating revenue, feeding a shared treasury. Built for AgentProof.

## Agents

| Agent | Job | Cycle |
|-------|-----|-------|
| **Scout** | Finds tasks agents can complete (X, Upwork, marketplaces) | Every 2 hours |
| **Worker** | Picks tasks, completes them (scraping, data extraction, automation), logs income | Continuous (60s poll) |
| **BD** | Finds projects needing AgentProof trust scores, drafts outreach | Every 2 hours |

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium  # optional, for advanced scraping

# 2. Configure environment
cp .env.example .env
# Fill in all API keys

# 3. Run Supabase migration
# Copy migrations/001_create_tables.sql into your Supabase SQL editor and run it

# 4. Seed first prospect (Quantu)
cd agent_town
python -m agents.bd.bd --seed-quantu

# 5. Approve outreach drafts
python -m agents.bd.approve

# 6. Start all agents
python scheduler.py
```

## Individual Agent Commands

```bash
# Scout — run one cycle
python -m agents.scout.scout

# Worker — run one cycle or continuous
python -m agents.worker.worker --once
python -m agents.worker.worker

# BD — run one cycle or seed Quantu
python -m agents.bd.bd --cycle
python -m agents.bd.bd --seed-quantu

# BD approval queue
python -m agents.bd.approve

# Weekly report
python report.py --preview    # print HTML
python report.py --send       # email via Resend
```

## Architecture

```
shared/          Supabase client, Anthropic client, treasury, messaging, config
agents/scout/    X monitor, marketplace crawler, opportunity evaluator
agents/worker/   Task scorer, skill executor (scrape, extract, enrich, automate)
agents/bd/       X monitor, CRM, outreach drafter, approval CLI
scheduler.py     Thread-per-agent, self-healing restarts, weekly report schedule
report.py        Weekly email via Resend
migrations/      Supabase SQL
```

## Agent Communication

Agents communicate via Supabase tables:
- **Scout → Worker**: writes to `opportunities` table
- **Worker → Treasury**: writes to `treasury` table
- **Worker → Scout**: sends `task_feedback` messages on failure
- **BD → Approval queue**: writes to `outreach_log` with `approved=false`
- **All agents**: use `agent_messages` table for inter-agent comms

## Self-Healing

The scheduler monitors all agent threads every 30 seconds. If any thread dies:
1. Logs the crash
2. Applies exponential backoff (2^n seconds, max 5 minutes)
3. Restarts the agent thread
4. Resets backoff on successful cycle

## Logs

Each agent writes to `agent_town/logs/{agent_name}.log`. All runs also tracked in `agent_runs` Supabase table.
