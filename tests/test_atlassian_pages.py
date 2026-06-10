from unittest.mock import MagicMock

from ghostbrain.connectors.atlassian._base import AtlassianClient
from ghostbrain.connectors.atlassian.pages import PageGone, create_page, update_page


def _client_returning(*responses):
    client = AtlassianClient("x.atlassian.net", "e@x.com", "tok")
    mocks = []
    for status, body in responses:
        r = MagicMock(status_code=status, text="")
        r.json.return_value = body
        mocks.append(r)
    client._session.request = MagicMock(side_effect=mocks)
    return client, client._session.request


def test_create_page_posts_storage_body():
    client, req = _client_returning((200, {"id": "123", "_links": {"base": "https://x.atlassian.net/wiki", "webui": "/spaces/K/pages/123"}}))
    out = create_page(client, space_key="K", title="T", storage_html="<p>hi</p>", parent_id="9")
    assert out["page_id"] == "123"
    assert out["url"] == "https://x.atlassian.net/wiki/spaces/K/pages/123"
    sent = req.call_args.kwargs.get("json") or req.call_args[1].get("json")
    assert sent["space"]["key"] == "K"
    assert sent["ancestors"] == [{"id": "9"}]
    assert sent["body"]["storage"]["value"] == "<p>hi</p>"


def test_update_page_increments_version():
    client, req = _client_returning(
        (200, {"id": "123", "version": {"number": 4}, "title": "T"}),
        (200, {"id": "123", "_links": {"base": "https://x.atlassian.net/wiki", "webui": "/x"}}),
    )
    update_page(client, page_id="123", title="T2", storage_html="<p>v2</p>")
    put_body = req.call_args_list[1].kwargs.get("json") or req.call_args_list[1][1]["json"]
    assert put_body["version"]["number"] == 5
    assert put_body["title"] == "T2"


def test_update_page_404_raises_page_gone():
    client, req = _client_returning((404, {}))
    try:
        update_page(client, page_id="123", title="T", storage_html="x")
        assert False, "expected PageGone"
    except PageGone:
        pass
