ALTER TABLE analysis_jobs
    ADD COLUMN crop_code TEXT,
    ADD COLUMN model_name TEXT,
    ADD COLUMN model_version TEXT,
    ADD COLUMN confidence_threshold NUMERIC(4, 3) NOT NULL DEFAULT 0.250
        CHECK (confidence_threshold > 0 AND confidence_threshold <= 1);

CREATE TABLE analysis_detections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    class_id INTEGER NOT NULL,
    class_name TEXT NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    bounding_box JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX analysis_detections_job_id_idx ON analysis_detections (job_id);

ALTER TABLE analysis_detections ENABLE ROW LEVEL SECURITY;
