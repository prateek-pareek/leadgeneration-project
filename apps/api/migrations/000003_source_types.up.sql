-- Expand allowed source types to match worker connectors and UI

ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_type_check;

ALTER TABLE sources ADD CONSTRAINT sources_type_check CHECK (
  type IN (
    'hackernews', 'reddit', 'linkedin', 'twitter', 'x', 'threads',
    'producthunt', 'devto', 'google_places', 'job_portals', 'freelance_marketplaces',
    'indiehackers', 'github', 'manual'
  )
);
