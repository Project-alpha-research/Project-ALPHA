"""Proof change for the merge queue. It must never land: the pull request is closed after the proof."""

import os


def test_this_change_is_refused_by_the_merge_queue() -> None:
    # Passes in the pull-request check, fails in the queue's run of the commit that would land.
    assert os.environ.get("GITHUB_EVENT_NAME") != "merge_group"
