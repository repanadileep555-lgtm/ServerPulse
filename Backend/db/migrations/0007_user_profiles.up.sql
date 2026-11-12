-- Editable profile details for dashboard accounts.
-- The avatar is a small base64 image data URL produced by the dashboard.

ALTER TABLE users ADD COLUMN display_name TEXT;
ALTER TABLE users ADD COLUMN avatar TEXT;
