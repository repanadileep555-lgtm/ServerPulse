ALTER TABLE hosts ADD COLUMN long_running_seconds INTEGER NOT NULL DEFAULT 3600
    CHECK (long_running_seconds BETWEEN 60 AND 31536000);

CREATE TABLE monitoring_samples (
    id INTEGER PRIMARY KEY,
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    sampled_at TEXT NOT NULL,
    received_at TEXT NOT NULL,
    cpu_percent REAL NOT NULL CHECK (cpu_percent BETWEEN 0 AND 100),
    memory_total_bytes INTEGER NOT NULL CHECK (memory_total_bytes > 0),
    memory_available_bytes INTEGER NOT NULL CHECK (memory_available_bytes >= 0),
    memory_used_bytes INTEGER NOT NULL CHECK (memory_used_bytes >= 0),
    memory_percent REAL NOT NULL CHECK (memory_percent BETWEEN 0 AND 100),
    process_count INTEGER NOT NULL CHECK (process_count >= 0),
    denied_count INTEGER NOT NULL CHECK (denied_count >= 0),
    vanished_count INTEGER NOT NULL CHECK (vanished_count >= 0),
    long_running_count INTEGER NOT NULL CHECK (long_running_count >= 0),
    zombie_count INTEGER CHECK (zombie_count >= 0),
    CHECK (memory_available_bytes + memory_used_bytes = memory_total_bytes)
);

CREATE INDEX ix_monitoring_samples_host_time ON monitoring_samples(host_id, sampled_at, id);

CREATE TABLE process_samples (
    sample_id INTEGER NOT NULL REFERENCES monitoring_samples(id) ON DELETE CASCADE,
    pid INTEGER NOT NULL CHECK (pid >= 0),
    create_time TEXT,
    name TEXT,
    status TEXT,
    cpu_percent REAL CHECK (cpu_percent BETWEEN 0 AND 100),
    rss_bytes INTEGER CHECK (rss_bytes >= 0),
    memory_percent REAL CHECK (memory_percent BETWEEN 0 AND 100),
    runtime_seconds REAL CHECK (runtime_seconds >= 0),
    long_running INTEGER CHECK (long_running IN (0, 1)),
    zombie INTEGER CHECK (zombie IN (0, 1)),
    access_denied INTEGER NOT NULL CHECK (access_denied IN (0, 1)),
    PRIMARY KEY (sample_id, pid)
);

CREATE INDEX ix_process_samples_identity ON process_samples(pid, create_time, sample_id);

CREATE TABLE monitoring_receipts (
    host_id INTEGER NOT NULL REFERENCES hosts(id) ON DELETE CASCADE,
    batch_id TEXT NOT NULL,
    payload_digest TEXT NOT NULL,
    sample_id INTEGER REFERENCES monitoring_samples(id) ON DELETE SET NULL,
    accepted_at TEXT NOT NULL,
    PRIMARY KEY (host_id, batch_id)
);
