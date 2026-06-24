-- Migration: 001_initial_schema
-- ProspectOS complete initial schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- CORE IDENTITY
-- ============================================================

CREATE TABLE organizations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT NOT NULL,
  slug            TEXT UNIQUE NOT NULL,
  plan            TEXT NOT NULL DEFAULT 'free',
  settings        JSONB NOT NULL DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);

CREATE TABLE users (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  email           TEXT UNIQUE NOT NULL,
  name            TEXT NOT NULL,
  avatar_url      TEXT,
  role            TEXT NOT NULL DEFAULT 'member',
  password_hash   TEXT NOT NULL,
  totp_secret     TEXT,
  last_login_at   TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ,
  CONSTRAINT users_role_check CHECK (role IN ('owner','admin','member','viewer'))
);

CREATE INDEX users_org_id_idx ON users(org_id);
CREATE INDEX users_email_idx ON users(email);

CREATE TABLE sessions (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash      TEXT NOT NULL UNIQUE,
  ip_address      INET,
  user_agent      TEXT,
  expires_at      TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX sessions_user_id_idx ON sessions(user_id);
CREATE INDEX sessions_token_hash_idx ON sessions(token_hash);

-- ============================================================
-- SOURCES
-- ============================================================

CREATE TABLE sources (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  name            TEXT NOT NULL,
  type            TEXT NOT NULL,
  config          JSONB NOT NULL DEFAULT '{}',
  is_active       BOOLEAN NOT NULL DEFAULT true,
  last_run_at     TIMESTAMPTZ,
  next_run_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT sources_type_check CHECK (
    type IN ('hackernews','reddit','x','producthunt','indiehackers','github','manual')
  )
);

CREATE INDEX sources_org_id_idx ON sources(org_id);

-- ============================================================
-- AUTHORS / LEADS
-- ============================================================

CREATE TABLE authors (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  platform        TEXT NOT NULL,
  handle          TEXT NOT NULL,
  display_name    TEXT,
  profile_url     TEXT,
  bio             TEXT,
  followers_count INTEGER,
  website         TEXT,
  location        TEXT,
  raw_profile     JSONB,
  embedding       vector(1536),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(org_id, platform, handle)
);

CREATE TABLE companies (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  name            TEXT NOT NULL,
  website         TEXT,
  domain          TEXT,
  description     TEXT,
  stage           TEXT,
  size_estimate   TEXT,
  industry        TEXT,
  linkedin_url    TEXT,
  twitter_handle  TEXT,
  github_org      TEXT,
  raw_data        JSONB,
  embedding       vector(1536),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT companies_stage_check CHECK (
    stage IN ('idea','pre-seed','seed','early','growth','unknown') OR stage IS NULL
  )
);

CREATE INDEX companies_org_id_idx ON companies(org_id);

CREATE TABLE posts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  source_id       UUID REFERENCES sources(id),
  author_id       UUID REFERENCES authors(id),
  external_id     TEXT,
  platform        TEXT NOT NULL,
  url             TEXT NOT NULL,
  text            TEXT NOT NULL,
  title           TEXT,
  posted_at       TIMESTAMPTZ,
  engagement      JSONB DEFAULT '{}',
  language        TEXT DEFAULT 'en',
  source_confidence DECIMAL(4,3),
  raw_data        JSONB,
  embedding       vector(1536),
  is_processed    BOOLEAN NOT NULL DEFAULT false,
  discovered_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(org_id, platform, external_id)
);

CREATE INDEX posts_org_posted_at_idx ON posts(org_id, posted_at DESC);
CREATE INDEX posts_org_processed_idx ON posts(org_id, is_processed);
CREATE INDEX posts_embedding_idx ON posts USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- LEADS
-- ============================================================

CREATE TABLE leads (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  author_id       UUID REFERENCES authors(id),
  company_id      UUID REFERENCES companies(id),
  post_id         UUID REFERENCES posts(id),
  source          TEXT NOT NULL,
  status          TEXT NOT NULL DEFAULT 'active',
  pipeline_stage  TEXT NOT NULL DEFAULT 'Discovered',
  owner_id        UUID REFERENCES users(id),
  tags            TEXT[] DEFAULT '{}',
  next_action     TEXT,
  next_action_at  TIMESTAMPTZ,
  last_contact_at TIMESTAMPTZ,
  is_suppressed   BOOLEAN NOT NULL DEFAULT false,
  suppressed_at   TIMESTAMPTZ,
  suppression_reason TEXT,
  custom_fields   JSONB DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);

CREATE INDEX leads_org_stage_idx ON leads(org_id, pipeline_stage) WHERE deleted_at IS NULL;
CREATE INDEX leads_org_owner_idx ON leads(org_id, owner_id) WHERE deleted_at IS NULL;
CREATE INDEX leads_org_created_idx ON leads(org_id, created_at DESC) WHERE deleted_at IS NULL;
CREATE INDEX leads_org_suppressed_idx ON leads(org_id, is_suppressed);

-- ============================================================
-- RESEARCH
-- ============================================================

CREATE TABLE research_briefs (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id             UUID NOT NULL REFERENCES leads(id),
  org_id              UUID NOT NULL REFERENCES organizations(id),
  company_name        TEXT,
  company_description TEXT,
  company_stage       TEXT,
  company_size        TEXT,
  founder_confidence  DECIMAL(4,3),
  is_decision_maker   BOOLEAN,
  pain_points         TEXT[],
  budget_signal       TEXT,
  tech_maturity       TEXT,
  service_fit         TEXT[],
  engagement_angle    TEXT,
  brief_text          TEXT,
  confidence_overall  DECIMAL(4,3),
  uncertain_fields    TEXT[],
  sources_used        TEXT[],
  model_used          TEXT,
  raw_output          JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX research_briefs_lead_id_idx ON research_briefs(lead_id);
CREATE INDEX research_briefs_org_id_idx ON research_briefs(org_id);

-- ============================================================
-- SCORING
-- ============================================================

CREATE TABLE lead_scores (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id           UUID NOT NULL REFERENCES leads(id),
  org_id            UUID NOT NULL REFERENCES organizations(id),
  score             INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
  bucket            TEXT NOT NULL,
  score_version     TEXT NOT NULL DEFAULT 'v1',
  dimension_scores  JSONB NOT NULL DEFAULT '{}',
  top_signals       TEXT[],
  explanation       TEXT,
  recommended_action TEXT,
  model_used        TEXT,
  scored_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT lead_scores_bucket_check CHECK (bucket IN ('hot','warm','cold','ignore'))
);

CREATE INDEX lead_scores_lead_id_idx ON lead_scores(lead_id);
CREATE INDEX lead_scores_org_score_idx ON lead_scores(org_id, score DESC);

-- ============================================================
-- COMMENT DRAFTS
-- ============================================================

CREATE TABLE comment_drafts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id         UUID NOT NULL REFERENCES leads(id),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  post_id         UUID REFERENCES posts(id),
  variants        JSONB NOT NULL DEFAULT '[]',
  selected_variant JSONB,
  context_used    TEXT,
  model_used      TEXT,
  status          TEXT NOT NULL DEFAULT 'pending_approval',
  approved_by     UUID REFERENCES users(id),
  approved_at     TIMESTAMPTZ,
  posted_at       TIMESTAMPTZ,
  posted_url      TEXT,
  rejection_reason TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT comment_drafts_status_check CHECK (
    status IN ('pending_approval','approved','rejected','posted','cancelled')
  )
);

CREATE INDEX comment_drafts_org_status_idx ON comment_drafts(org_id, status, created_at DESC);
CREATE INDEX comment_drafts_lead_id_idx ON comment_drafts(lead_id);

-- ============================================================
-- OUTREACH DRAFTS
-- ============================================================

CREATE TABLE outreach_drafts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  lead_id         UUID NOT NULL REFERENCES leads(id),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  type            TEXT NOT NULL,
  subject         TEXT,
  body            TEXT NOT NULL,
  personalization_notes TEXT,
  context_used    TEXT,
  model_used      TEXT,
  status          TEXT NOT NULL DEFAULT 'pending_approval',
  approved_by     UUID REFERENCES users(id),
  approved_at     TIMESTAMPTZ,
  sent_at         TIMESTAMPTZ,
  sent_via        TEXT,
  rejection_reason TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT outreach_drafts_type_check CHECK (
    type IN ('linkedin_dm','x_dm','cold_email','followup_email','meeting_followup','proposal_intro')
  ),
  CONSTRAINT outreach_drafts_status_check CHECK (
    status IN ('pending_approval','approved','rejected','sent','cancelled')
  )
);

CREATE INDEX outreach_drafts_org_status_idx ON outreach_drafts(org_id, status, created_at DESC);
CREATE INDEX outreach_drafts_lead_id_idx ON outreach_drafts(lead_id);

-- ============================================================
-- EMAIL HEALTH
-- ============================================================

CREATE TABLE email_accounts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  label           TEXT NOT NULL,
  email_address   TEXT NOT NULL,
  domain          TEXT NOT NULL,
  smtp_host       TEXT,
  smtp_port       INTEGER,
  smtp_user       TEXT,
  smtp_pass_enc   TEXT,
  imap_host       TEXT,
  imap_port       INTEGER,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  daily_limit     INTEGER NOT NULL DEFAULT 30,
  warmup_status   TEXT DEFAULT 'not_started',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT email_accounts_warmup_check CHECK (
    warmup_status IN ('not_started','warming','warm','degraded')
  )
);

CREATE INDEX email_accounts_org_id_idx ON email_accounts(org_id);

CREATE TABLE domains (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  domain          TEXT NOT NULL,
  is_primary      BOOLEAN NOT NULL DEFAULT false,
  health_score    INTEGER,
  last_checked_at TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(org_id, domain)
);

CREATE TABLE domain_checks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  domain_id       UUID NOT NULL REFERENCES domains(id),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  spf_valid       BOOLEAN,
  spf_record      TEXT,
  dkim_valid      BOOLEAN,
  dkim_selectors  TEXT[],
  dmarc_valid     BOOLEAN,
  dmarc_policy    TEXT,
  mx_records      TEXT[],
  blacklists_hit  TEXT[],
  blacklist_clean BOOLEAN,
  health_score    INTEGER,
  raw_results     JSONB,
  checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX domain_checks_domain_id_idx ON domain_checks(domain_id, checked_at DESC);

-- ============================================================
-- CRM / ACTIVITIES
-- ============================================================

CREATE TABLE activities (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  lead_id         UUID REFERENCES leads(id),
  user_id         UUID REFERENCES users(id),
  type            TEXT NOT NULL,
  title           TEXT,
  description     TEXT,
  metadata        JSONB DEFAULT '{}',
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX activities_lead_id_idx ON activities(lead_id, created_at DESC);
CREATE INDEX activities_org_id_idx ON activities(org_id, created_at DESC);

CREATE TABLE tasks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  lead_id         UUID REFERENCES leads(id),
  assigned_to     UUID REFERENCES users(id),
  title           TEXT NOT NULL,
  description     TEXT,
  due_at          TIMESTAMPTZ,
  priority        TEXT DEFAULT 'medium',
  status          TEXT NOT NULL DEFAULT 'open',
  completed_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT tasks_priority_check CHECK (priority IN ('low','medium','high')),
  CONSTRAINT tasks_status_check CHECK (status IN ('open','done','cancelled'))
);

CREATE INDEX tasks_org_status_idx ON tasks(org_id, status, due_at);
CREATE INDEX tasks_lead_id_idx ON tasks(lead_id);

CREATE TABLE notes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  lead_id         UUID REFERENCES leads(id),
  author_id       UUID REFERENCES users(id),
  body            TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at      TIMESTAMPTZ
);

CREATE INDEX notes_lead_id_idx ON notes(lead_id, created_at DESC) WHERE deleted_at IS NULL;

-- ============================================================
-- APPROVALS
-- ============================================================

CREATE TABLE approvals (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  type            TEXT NOT NULL,
  ref_id          UUID NOT NULL,
  lead_id         UUID REFERENCES leads(id),
  status          TEXT NOT NULL DEFAULT 'pending',
  assigned_to     UUID REFERENCES users(id),
  decided_by      UUID REFERENCES users(id),
  decision_at     TIMESTAMPTZ,
  decision_notes  TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT approvals_type_check CHECK (type IN ('comment_draft','outreach_draft')),
  CONSTRAINT approvals_status_check CHECK (status IN ('pending','approved','rejected'))
);

CREATE INDEX approvals_org_status_idx ON approvals(org_id, status, created_at DESC);
CREATE INDEX approvals_ref_id_idx ON approvals(ref_id);

-- ============================================================
-- AUDIT LOG
-- ============================================================

CREATE TABLE audit_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  user_id         UUID REFERENCES users(id),
  action          TEXT NOT NULL,
  resource_type   TEXT,
  resource_id     UUID,
  before_state    JSONB,
  after_state     JSONB,
  ip_address      INET,
  user_agent      TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX audit_events_org_created_idx ON audit_events(org_id, created_at DESC);
CREATE INDEX audit_events_resource_idx ON audit_events(org_id, resource_type, resource_id);
CREATE INDEX audit_events_user_id_idx ON audit_events(user_id, created_at DESC);

-- ============================================================
-- SUPPRESSION
-- ============================================================

CREATE TABLE suppression_list (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  type            TEXT NOT NULL,
  value           TEXT NOT NULL,
  reason          TEXT,
  added_by        UUID REFERENCES users(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE(org_id, type, value),
  CONSTRAINT suppression_type_check CHECK (type IN ('email','domain','handle','company'))
);

CREATE INDEX suppression_org_type_idx ON suppression_list(org_id, type);

-- ============================================================
-- ALERTS
-- ============================================================

CREATE TABLE alerts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  type            TEXT NOT NULL,
  severity        TEXT NOT NULL DEFAULT 'info',
  title           TEXT NOT NULL,
  description     TEXT,
  resource_type   TEXT,
  resource_id     UUID,
  is_read         BOOLEAN NOT NULL DEFAULT false,
  resolved_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT alerts_severity_check CHECK (severity IN ('info','warning','critical'))
);

CREATE INDEX alerts_org_unread_idx ON alerts(org_id, is_read, created_at DESC);

-- ============================================================
-- INTEGRATIONS
-- ============================================================

CREATE TABLE integrations (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id          UUID NOT NULL REFERENCES organizations(id),
  type            TEXT NOT NULL,
  label           TEXT,
  config          JSONB NOT NULL DEFAULT '{}',
  secrets_enc     JSONB DEFAULT '{}',
  is_active       BOOLEAN NOT NULL DEFAULT true,
  last_used_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX integrations_org_id_idx ON integrations(org_id);
