from unittest.mock import MagicMock, patch

import pytest

from ghostbrain.api.repo import export_confluence, notes_manual
from ghostbrain.connectors.atlassian.pages import PageGone


def _patch_client():
    return patch.object(export_confluence, "_client_for_space", return_value=MagicMock())


def test_export_creates_and_stamps(vault):
    rec = notes_manual.write_inbox_jot("# RFC Title\n\nbody")
    with _patch_client(), patch.object(
        export_confluence.pages, "create_page",
        return_value={"page_id": "42", "url": "https://x/wiki/42"},
    ) as create:
        out = export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=False)
    assert out["page_id"] == "42" and out["action"] == "created"
    assert create.call_args.kwargs["title"] == "RFC Title"
    fm = notes_manual.read_jot(rec["id"])["frontmatter"]
    assert fm["confluence_page_id"] == "42" and fm["confluence_url"] == "https://x/wiki/42"


def test_reexport_updates_tracked_page(vault):
    rec = notes_manual.write_inbox_jot("# T\n\nv1")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "42"})
    with _patch_client(), patch.object(
        export_confluence.pages, "update_page",
        return_value={"page_id": "42", "url": "https://x/wiki/42"},
    ):
        out = export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=False)
    assert out["action"] == "updated"


def test_tracked_page_gone_raises(vault):
    rec = notes_manual.write_inbox_jot("# T\n\nv1")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "42"})
    with _patch_client(), patch.object(
        export_confluence.pages, "update_page", side_effect=PageGone("42"),
    ):
        with pytest.raises(export_confluence.TrackedPageGone):
            export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=False)
    assert notes_manual.read_jot(rec["id"])["frontmatter"]["confluence_page_id"] == "42"


def test_force_new_creates_despite_tracking(vault):
    rec = notes_manual.write_inbox_jot("# T\n\nv1")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "42"})
    with _patch_client(), patch.object(
        export_confluence.pages, "create_page",
        return_value={"page_id": "99", "url": "https://x/wiki/99"},
    ):
        out = export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=True)
    assert out["action"] == "created" and out["page_id"] == "99"
