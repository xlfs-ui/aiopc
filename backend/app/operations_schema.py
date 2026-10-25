"""Schema v5: explicit workforce assignments and account-scoped notifications."""
TICKET_COLUMNS={
    'assigned_staff_id':"TEXT NOT NULL DEFAULT ''",
    'resolution':"TEXT NOT NULL DEFAULT ''",
    'due_at':"TEXT NOT NULL DEFAULT ''",
    'version':'INTEGER NOT NULL DEFAULT 0',
}
SCHEMA=[
    "CREATE TABLE IF NOT EXISTS service_staff (id TEXT PRIMARY KEY, name TEXT NOT NULL, team TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', user_id TEXT UNIQUE REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, recipient_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, event_key TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, resource_id TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT NOT NULL DEFAULT '', UNIQUE(recipient_id,event_key))",
    'CREATE INDEX IF NOT EXISTS notifications_recipient ON notifications(recipient_id,created_at)',
    'CREATE INDEX IF NOT EXISTS ticket_assigned_staff ON tickets(assigned_staff_id,status)',
]
