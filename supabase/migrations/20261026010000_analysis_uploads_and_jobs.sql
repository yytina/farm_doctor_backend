CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Source files submitted for fire-blight analysis.
CREATE TABLE IF NOT EXISTS analysis_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    storage_path TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL,
    content_type TEXT,
    size_bytes BIGINT NOT NULL CHECK (size_bytes > 0),
    orchard_name TEXT,
    collection_date DATE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A job is created immediately after an upload. An inference worker advances it
-- through queued -> processing -> completed/failed.
CREATE TABLE IF NOT EXISTS analysis_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id UUID NOT NULL UNIQUE REFERENCES analysis_uploads(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'completed', 'failed')),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error_message TEXT,
    result_summary JSONB,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS analysis_uploads_user_created_at_idx
    ON analysis_uploads (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS analysis_jobs_user_status_created_at_idx
    ON analysis_jobs (user_id, status, created_at DESC);

-- Uploaded images and datasets must only be accessed by the server-side API.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'analysis-uploads',
    'analysis-uploads',
    false,
    10485760,
    ARRAY['text/csv', 'image/jpeg', 'image/png']
)
ON CONFLICT (id) DO NOTHING;

ALTER TABLE analysis_uploads ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_jobs ENABLE ROW LEVEL SECURITY;
