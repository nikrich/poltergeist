"""GET /v1/captures and GET /v1/captures/{id}."""
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_inbox(
    vault: Path,
    source: str,
    capture_id: str,
    frontmatter_dict: dict,
    body: str = "",
) -> Path:
    """Write an inbox markdown file with YAML frontmatter.

    Quotes string values so colon-containing ISO timestamps are valid YAML.
    """
    raw = vault / "00-inbox" / "raw" / source
    raw.mkdir(parents=True, exist_ok=True)
    p = raw / f"{capture_id}.md"
    lines = []
    for k, v in frontmatter_dict.items():
        if isinstance(v, str):
            # Always single-quote strings to keep YAML parsing predictable
            # (escape internal single quotes by doubling them).
            escaped = v.replace("'", "''")
            lines.append(f"{k}: '{escaped}'")
        else:
            lines.append(f"{k}: {v}")
    fm_yaml = "\n".join(lines)
    p.write_text(f"---\n{fm_yaml}\n---\n\n{body}\n")
    return p


def test_empty_returns_zero_total(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/captures", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_inbox_items_appear(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat()
    _write_inbox(
        tmp_vault,
        "gmail",
        "p1",
        {
            "id": "p1",
            "source": "gmail",
            "title": "re: design crit",
            "context": "personal",
            "type": "email",
            "ingestedAt": now,
        },
        body="works for me — moving the 11am to thursday next week.",
    )
    res = client.get("/v1/captures", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "re: design crit"
    # `from` is "personal · <time>"
    assert data["items"][0]["from"].startswith("personal")
    assert data["items"][0]["unread"] is True
    # First non-blank, non-heading body line becomes the snippet
    assert "works for me" in data["items"][0]["snippet"]
    assert data["items"][0]["tags"] == ["email"]


def test_limit_caps_results(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat()
    for i in range(10):
        _write_inbox(
            tmp_vault,
            "gmail",
            f"p{i}",
            {
                "id": f"p{i}",
                "source": "gmail",
                "title": f"item {i}",
                "context": "personal",
                "ingestedAt": now,
            },
            body=f"body {i}",
        )
    res = client.get("/v1/captures?limit=3", headers=auth_headers)
    data = res.json()
    assert data["total"] == 10
    assert len(data["items"]) == 3


def test_source_filter(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat()
    _write_inbox(
        tmp_vault,
        "gmail",
        "g1",
        {"id": "g1", "source": "gmail", "title": "x", "ingestedAt": now},
        body="x",
    )
    _write_inbox(
        tmp_vault,
        "slack",
        "s1",
        {"id": "s1", "source": "slack", "title": "y", "ingestedAt": now},
        body="y",
    )
    res = client.get("/v1/captures?source=slack", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    assert all(i["source"] == "slack" for i in data["items"])


def test_capture_detail_includes_body(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat()
    body = "full body text of the email"
    _write_inbox(
        tmp_vault,
        "gmail",
        "p1",
        {
            "id": "p1",
            "source": "gmail",
            "title": "subject",
            "ingestedAt": now,
        },
        body=body,
    )
    res = client.get("/v1/captures/p1", headers=auth_headers)
    assert res.status_code == 200
    assert body in res.json()["body"]


def test_capture_detail_404(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/captures/does-not-exist", headers=auth_headers)
    assert res.status_code == 404
