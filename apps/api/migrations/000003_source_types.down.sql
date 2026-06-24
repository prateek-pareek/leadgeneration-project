ALTER TABLE sources DROP CONSTRAINT IF EXISTS sources_type_check;

ALTER TABLE sources ADD CONSTRAINT sources_type_check CHECK (
  type IN ('hackernews','reddit','x','producthunt','indiehackers','github','manual')
);
