from __future__ import annotations

import pytest
from pydantic import ValidationError

from radaragent.subscriptions.models import Channel, SubscriptionCreate, SubscriptionFilter


def test_filter_defaults():
    f = SubscriptionFilter()
    assert f.min_score == 6.0
    assert f.keywords_boost == []
    assert f.source_whitelist == []


def test_filter_min_score_range():
    with pytest.raises(ValidationError):
        SubscriptionFilter(min_score=11)
    with pytest.raises(ValidationError):
        SubscriptionFilter(min_score=-1)


def test_subscription_create_valid():
    sub = SubscriptionCreate(
        user_id=1,
        name="AI news",
        interest_profile="LLM agents and inference infra",
        filter=SubscriptionFilter(min_score=7),
        schedule="0 8 * * *",
        channels=[Channel(type="email", config={"to": "me@x.com"})],
        format="digest",
    )
    assert sub.schedule == "0 8 * * *"


def test_subscription_create_bad_cron_rejected():
    with pytest.raises(ValidationError, match="cron"):
        SubscriptionCreate(
            user_id=1,
            name="x",
            interest_profile="y",
            schedule="not a cron",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        )


def test_subscription_create_bad_format_rejected():
    with pytest.raises(ValidationError):
        SubscriptionCreate(
            user_id=1,
            name="x",
            interest_profile="y",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
            format="bogus",
        )
