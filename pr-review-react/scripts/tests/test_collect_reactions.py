import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from collect_reactions import (
    extract_pattern_name,
    compute_delta_from_reactions,
    apply_deltas,
    load_scores,
    SCORE_THUMBS_UP,
    SCORE_THUMBS_DOWN,
)


# ---------------------------------------------------------------------------
# extract_pattern_name
# ---------------------------------------------------------------------------

def test_extracts_pattern_from_html_comment():
    body = "Some finding\n<!-- pr-review-pattern: Missing null checks -->"
    assert extract_pattern_name(body) == "Missing null checks"


def test_extracts_pattern_with_extra_whitespace():
    body = "<!--   pr-review-pattern:   Trailing space   -->"
    assert extract_pattern_name(body) == "Trailing space"


def test_returns_none_when_no_marker():
    assert extract_pattern_name("No marker here") is None


def test_returns_none_for_empty_body():
    assert extract_pattern_name("") is None


def test_extracts_first_pattern_when_multiple():
    body = (
        "<!-- pr-review-pattern: First pattern -->\n"
        "<!-- pr-review-pattern: Second pattern -->"
    )
    assert extract_pattern_name(body) == "First pattern"


# ---------------------------------------------------------------------------
# compute_delta_from_reactions
# ---------------------------------------------------------------------------

def make_reaction(content, user_id):
    return {"content": content, "user": {"id": user_id}}


def test_two_up_one_down():
    reactions = [
        make_reaction("+1", 1),
        make_reaction("+1", 2),
        make_reaction("-1", 3),
    ]
    delta, up, down = compute_delta_from_reactions(reactions)
    assert up == 2
    assert down == 1
    assert delta == 2 * SCORE_THUMBS_UP + 1 * SCORE_THUMBS_DOWN


def test_duplicate_user_not_double_counted():
    reactions = [
        make_reaction("+1", 1),
        make_reaction("+1", 1),  # same user, same type
    ]
    delta, up, down = compute_delta_from_reactions(reactions)
    assert up == 1
    assert delta == SCORE_THUMBS_UP


def test_user_can_have_both_up_and_down():
    reactions = [
        make_reaction("+1", 1),
        make_reaction("-1", 1),  # same user, different types — both count
    ]
    delta, up, down = compute_delta_from_reactions(reactions)
    assert up == 1
    assert down == 1
    assert delta == SCORE_THUMBS_UP + SCORE_THUMBS_DOWN


def test_empty_reactions():
    delta, up, down = compute_delta_from_reactions([])
    assert delta == 0
    assert up == 0
    assert down == 0


def test_ignores_other_reaction_types():
    reactions = [
        make_reaction("heart", 1),
        make_reaction("rocket", 2),
        make_reaction("+1", 3),
    ]
    delta, up, down = compute_delta_from_reactions(reactions)
    assert up == 1
    assert down == 0


# ---------------------------------------------------------------------------
# apply_deltas
# ---------------------------------------------------------------------------

def test_apply_creates_new_pattern_entry():
    scores = {"version": 1, "patterns": {}}
    deltas = {"Missing null checks": {"delta": 4, "accepts": 2, "dismissals": 0, "prs": [1]}}
    result = apply_deltas(scores, deltas, "2026-08-22")
    entry = result["patterns"]["Missing null checks"]
    assert entry["score"] == 4
    assert entry["accepts"] == 2
    assert entry["dismissals"] == 0
    assert entry["lastSeen"] == "2026-08-22"


def test_apply_accumulates_on_existing_entry():
    scores = {
        "version": 1,
        "patterns": {
            "Missing null checks": {
                "score": 3, "accepts": 1, "dismissals": 1,
                "explicitlyIgnored": False, "source": "Phase 1", "lastSeen": "2026-08-01",
            }
        },
    }
    deltas = {"Missing null checks": {"delta": -1, "accepts": 0, "dismissals": 1, "prs": [5]}}
    result = apply_deltas(scores, deltas, "2026-08-22")
    entry = result["patterns"]["Missing null checks"]
    assert entry["score"] == 2
    assert entry["dismissals"] == 2
    assert entry["lastSeen"] == "2026-08-22"


def test_apply_preserves_explicitly_ignored_flag():
    scores = {
        "version": 1,
        "patterns": {
            "Some pattern": {
                "score": -5, "accepts": 0, "dismissals": 5,
                "explicitlyIgnored": True, "source": "Phase 1", "lastSeen": "2026-07-01",
            }
        },
    }
    deltas = {"Some pattern": {"delta": 2, "accepts": 1, "dismissals": 0, "prs": [10]}}
    result = apply_deltas(scores, deltas, "2026-08-22")
    assert result["patterns"]["Some pattern"]["explicitlyIgnored"] is True


def test_apply_multiple_patterns():
    scores = {"version": 1, "patterns": {}}
    deltas = {
        "Pattern A": {"delta": 4, "accepts": 2, "dismissals": 0, "prs": [1]},
        "Pattern B": {"delta": -1, "accepts": 0, "dismissals": 1, "prs": [2]},
    }
    result = apply_deltas(scores, deltas, "2026-08-22")
    assert result["patterns"]["Pattern A"]["score"] == 4
    assert result["patterns"]["Pattern B"]["score"] == -1