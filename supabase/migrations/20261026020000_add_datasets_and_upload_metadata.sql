CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- A dataset represents one field visit or collection session. It groups the
-- independently processed images/datasets submitted in that session.
CREATE TABLE datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT,
    orchard_name TEXT,
    collection_date DATE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (id, user_id)
);

ALTER TABLE analysis_uploads
    ADD COLUMN dataset_id UUID,
    ADD COLUMN metadata_version TEXT,
    ADD COLUMN detailed_project_number TEXT,
    ADD COLUMN source_data_type TEXT,
    ADD COLUMN damage_code TEXT,
    ADD COLUMN crop_code TEXT,
    ADD COLUMN crop_part_code TEXT,
    ADD COLUMN growth_stage_code TEXT,
    ADD COLUMN damage_severity_code TEXT,
    ADD COLUMN collector_id TEXT,
    ADD COLUMN capture_order TEXT,
    ADD COLUMN specimen_sequence TEXT,
    ADD COLUMN metadata_parse_status TEXT NOT NULL DEFAULT 'unparsed'
        CHECK (metadata_parse_status IN ('unparsed', 'parsed', 'invalid', 'manual')),
    ADD COLUMN metadata_parse_error TEXT;

-- Preserve every existing upload by giving it its own imported dataset. New
-- multi-file requests will instead create one dataset with many uploads.
INSERT INTO datasets (id, user_id, name, orchard_name, collection_date, created_at)
SELECT
    id,
    user_id,
    'Imported upload: ' || original_filename,
    orchard_name,
    collection_date,
    created_at
FROM analysis_uploads
WHERE dataset_id IS NULL;

UPDATE analysis_uploads
SET dataset_id = id
WHERE dataset_id IS NULL;

CREATE INDEX analysis_uploads_dataset_created_at_idx
    ON analysis_uploads (dataset_id, created_at DESC);
CREATE INDEX datasets_user_collection_date_idx
    ON datasets (user_id, collection_date DESC, created_at DESC);

ALTER TABLE datasets ENABLE ROW LEVEL SECURITY;
