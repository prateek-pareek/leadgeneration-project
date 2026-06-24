-- Add operational stats columns to sources table
-- posts_found: cumulative count of new posts/businesses discovered
-- last_error:  last connector error message (NULL = healthy)

ALTER TABLE sources
  ADD COLUMN IF NOT EXISTS posts_found  INTEGER,
  ADD COLUMN IF NOT EXISTS last_error   TEXT;
