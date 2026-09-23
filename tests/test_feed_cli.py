import pytest
from flat_detector.feed_cli import checked_config

def test_disabled_and_bounded_feed_worker_config():
    with pytest.raises(ValueError):checked_config({})
    with pytest.raises(ValueError):checked_config({"FD_FEED_SOURCE_KEY":"x","FD_FEED_URL":"url","FD_FEED_ORIGIN":"origin","FD_FEED_POLL_SECONDS":"10"})
    key,url,origin,interval,token_file=checked_config({"FD_FEED_SOURCE_KEY":"partner", "FD_FEED_URL":"https://partner.example.test/api/feed", "FD_FEED_ORIGIN":"https://partner.example.test"})
    assert (key,interval,token_file)==("partner",86400,None)
