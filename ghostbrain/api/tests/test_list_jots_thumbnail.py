"""TDD: list_jots should expose the first embedded image as `thumbnail`."""
from ghostbrain.api.repo import notes_manual


def test_list_jots_includes_first_image_thumbnail(tmp_vault):
    notes_manual.write_inbox_jot(
        "see this\n\n![x](90-meta/assets/jots/2026/06/a-1.jpg)\n"
    )
    page = notes_manual.list_jots(limit=10, offset=0)
    item = page["items"][0]
    assert item["thumbnail"] == "90-meta/assets/jots/2026/06/a-1.jpg"


def test_list_jots_thumbnail_none_when_no_image(tmp_vault):
    notes_manual.write_inbox_jot("no image here, just text")
    page = notes_manual.list_jots(limit=10, offset=0)
    item = page["items"][0]
    assert item["thumbnail"] is None
