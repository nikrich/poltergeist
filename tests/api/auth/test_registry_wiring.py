import pytest
import ghostbrain.api.auth.providers.register_all  # noqa: F401
from ghostbrain.api.auth import registry


@pytest.mark.parametrize("cid", [
    "gmail", "calendar", "slack", "joplin", "jira", "confluence",
    "outlook_mail", "teams_chat", "teams_meetings", "github", "claude_code",
])
def test_provider_registered(cid):
    assert registry.provider_for(cid) is not None
