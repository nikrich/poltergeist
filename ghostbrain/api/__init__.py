"""Read-only HTTP API exposing ghostbrain vault data to the desktop app.

This module is additive — it imports from existing ghostbrain.* but does
not modify any existing module's surface. Phase 2 extends this with write
endpoints, OAuth flows, and WebSocket events.
"""
