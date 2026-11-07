-- Creator stage is selected during onboarding and used by the workspace UI.
-- The default keeps accounts created by older clients valid.
ALTER TABLE accounts ADD COLUMN creator_stage TEXT NOT NULL DEFAULT 'starting'
  CHECK(creator_stage IN ('starting','operating','established'));
