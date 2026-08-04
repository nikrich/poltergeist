"""Calendar connectors. Each provider (google, ics, microsoft-graph)
emits events of source=calendar with a normalized shape so the worker
pipeline + digest integration is one code path."""
