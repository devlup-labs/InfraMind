
CREATE TABLE IF NOT EXISTS errors (
    error_id     BIGSERIAL PRIMARY KEY,
    metric_name  VARCHAR(100) NOT NULL,
    time         TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_value  DOUBLE PRECISION NOT NULL,
    solved       BOOLEAN NOT NULL DEFAULT FALSE
);