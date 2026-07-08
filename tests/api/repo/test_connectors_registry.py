from ghostbrain.api.repo.connectors import list_connectors, get_connector


def test_joplin_is_enumerated():
    ids = {c["id"] for c in list_connectors()}
    assert "joplin" in ids


def test_joplin_has_display_metadata():
    rec = get_connector("joplin")
    assert rec is not None
    assert rec["displayName"]
    assert rec["vaultDestination"].endswith("joplin/")
