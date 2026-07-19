"""Unit tests for subgate. No network access: everything here is pure logic.

Run with: python -m pytest -q
"""

import json
import os

import yaml

import subgate


# ---------------------------------------------------------------------------
# Name extraction
# ---------------------------------------------------------------------------

def test_extract_names_mixed_text():
    text = "\n".join([
        "check https://www.reddit.com/r/Foo_Bar/comments/abc/xyz",
        "also old.reddit.com/r/baz and a mention of r/Qux99 inline",
        "Quux",
        "# r/commented_out should be ignored",
        "your/thing and ur/nope must not match",
        "not-a-name-because-hyphens",
    ])
    assert subgate.extract_names(text) == {"Foo_Bar", "baz", "Qux99", "Quux"}


def test_extract_names_empty_and_comments():
    assert subgate.extract_names("") == set()
    assert subgate.extract_names("# just a comment\n#another") == set()


def test_candidate_variants():
    got = subgate.candidate_variants("some-sub", "Some Sub")
    assert got == {"some_sub", "somesub", "SomeSub", "Some_Sub"}
    assert subgate.candidate_variants("", "") == set()
    # Slugs that violate the name charset produce nothing
    assert subgate.candidate_variants("way-too-long-for-a-subreddit-name-x", None) == set()


# ---------------------------------------------------------------------------
# Verification state machine
# ---------------------------------------------------------------------------

def fresh_state():
    return {"version": 1, "updated_utc": None, "subs": {}}


def test_apply_verification_add_flip_and_gone():
    state = fresh_state()
    now = "2026-07-18T00:00:00Z"
    res = {"spicy": {"name": "Spicy", "over18": True, "subscribers": 10, "type": "public"}}
    added = subgate.apply_verification(state, res, {"spicy"}, 3, "test", now)
    assert added == 1
    assert state["subs"]["spicy"]["status"] == "nsfw"
    assert state["subs"]["spicy"]["sources"] == ["test"]

    # Flip to sfw on Reddit's signal
    res2 = {"spicy": {"name": "Spicy", "over18": False, "subscribers": 11, "type": "public"}}
    added2 = subgate.apply_verification(state, res2, {"spicy"}, 3, None, now)
    assert added2 == 0
    assert state["subs"]["spicy"]["status"] == "sfw"
    assert state["subs"]["spicy"]["misses"] == 0

    # Three consecutive misses mark it gone, not one or two
    for i in range(3):
        subgate.apply_verification(state, {}, {"spicy"}, 3, None, now)
        expected = "sfw" if i < 2 else "gone"
        assert state["subs"]["spicy"]["status"] == expected

    # A successful resolution afterwards revives it and resets misses
    subgate.apply_verification(state, res, {"spicy"}, 3, None, now)
    assert state["subs"]["spicy"]["status"] == "nsfw"
    assert state["subs"]["spicy"]["misses"] == 0


def test_apply_verification_unknown_absent_name_is_ignored():
    state = fresh_state()
    subgate.apply_verification(state, {}, {"neverexisted"}, 3, None, "2026-07-18T00:00:00Z")
    assert state["subs"] == {}


def test_children_to_results_shape():
    payload = {"data": {"children": [
        {"kind": "t5", "data": {"display_name": "Alpha", "over18": True,
                                "subscribers": 5, "subreddit_type": "public"}},
        {"kind": "t5", "data": {"display_name": "", "over18": True}},
    ]}}
    out = subgate.children_to_results(payload)
    assert list(out) == ["alpha"]
    assert out["alpha"]["name"] == "Alpha"
    assert out["alpha"]["over18"] is True


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------

def test_rule_line_format():
    assert subgate.rule_line("Some_Sub") == "||reddit.com/r/Some_Sub^"


def make_state_with(entries):
    state = fresh_state()
    for name, subs, status in entries:
        state["subs"][name.lower()] = {
            "name": name, "over18": status == "nsfw", "subscribers": subs,
            "status": status, "sources": [], "misses": 0,
            "first_seen_utc": "x", "last_verified_utc": "x",
        }
    return state


def test_build_entries_sort_force_and_dedupe():
    state = make_state_with([
        ("Small", 10, "nsfw"),
        ("Big", 9999, "nsfw"),
        ("Safe", 500, "sfw"),
        ("Dead", 500, "gone"),
    ])
    entries, forced = subgate.build_entries(state, {"Forced_One", "big", "bad name"})
    names = [e["name"] for e in entries]
    # Sorted by subscribers descending; forced (no subscriber count) sorts last;
    # "big" deduped case insensitively; "bad name" rejected by charset.
    assert names == ["Big", "Small", "Forced_One"]
    assert forced == 1


def test_write_list_header_and_cap(tmp_path):
    state = make_state_with([("A", 3, "nsfw"), ("B", 2, "nsfw"), ("C", 1, "nsfw")])
    entries, _ = subgate.build_entries(state, set())
    path = tmp_path / "out.txt"
    n = subgate.write_list(str(path), entries, "chrome", cap=2)
    assert n == 2
    lines = path.read_text().splitlines()
    assert lines[0] == "! Title: subgate (chrome)"
    assert "! Entry count: 2" in lines
    assert lines[-2:] == ["||reddit.com/r/A^", "||reddit.com/r/B^"]


def test_state_roundtrip(tmp_path):
    path = str(tmp_path / "state.json")
    state = fresh_state()
    state["subs"]["x"] = {"name": "X", "status": "nsfw", "sources": [], "misses": 0}
    subgate.save_state(state, path)
    loaded = subgate.load_state(path)
    assert loaded["subs"]["x"]["name"] == "X"
    assert loaded["updated_utc"]


# ---------------------------------------------------------------------------
# Config and repo hygiene
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def test_sources_yaml_loads_with_required_keys():
    cfg = subgate.load_config(os.path.join(REPO_ROOT, "sources.yaml"))
    for key in ("qpm_authenticated", "qpm_unauthenticated", "max_calls_per_run",
                "misses_before_gone", "chrome_max_rules", "scrape_weekday",
                "reddit_new_pages", "bootstrap", "sources"):
        assert key in cfg, f"missing config key {key}"
    names = {s["name"] for s in cfg["sources"]}
    assert {"manual", "nsfwdog", "postpone"} <= names
    for s in cfg["sources"]:
        assert s["type"] in subgate.SCRAPERS


def test_workflow_yaml_parses():
    path = os.path.join(REPO_ROOT, ".github", "workflows", "subgate.yml")
    with open(path, encoding="utf-8") as f:
        wf = yaml.safe_load(f)
    assert "jobs" in wf and "build" in wf["jobs"]


# ---------------------------------------------------------------------------
# Mocked full-pipeline end to end (no network; Reddit-shaped payloads)
# ---------------------------------------------------------------------------

FAKE_SUBS = {
    "gonewild": ("gonewild", True, 3400000),
    "nsfw": ("NSFW", True, 2000000),
    "freshspice": ("FreshSpice", True, 5),
    "python": ("Python", False, 1300000),
    "construction": ("Construction", False, 200000),
    "estimators": ("estimators", False, 8000),
    "dataisbeautiful": ("dataisbeautiful", False, 1000000),
    # zz_ghost_zz deliberately absent: never resolves
}


def _t5(name, over18, subs):
    return {"kind": "t5", "data": {"display_name": name, "over18": over18,
                                   "subscribers": subs, "subreddit_type": "public"}}


def _fake_get_json(self, path, params=None):
    params = params or {}
    if path == "/subreddits/new":
        return {"data": {"children": [_t5("FreshSpice", True, 5)], "after": None}}
    if path == "/api/info":
        children = []
        for n in params.get("sr_name", "").split(","):
            hit = FAKE_SUBS.get(n.lower())
            if hit:
                children.append(_t5(*hit))
        return {"data": {"children": children, "after": None}}
    raise AssertionError(f"unexpected path in mocked pipeline: {path}")


def test_full_pipeline_mocked(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources.yaml").write_text(
        "qpm_authenticated: 6000\nqpm_unauthenticated: 6000\n"
        "max_calls_per_run: 50\nmisses_before_gone: 3\nchrome_max_rules: 3\n"
        "scrape_weekday: 6\nreddit_new_pages: 1\nbootstrap: {}\n"
        "sources:\n  - {name: manual, type: manual, path: manual_seeds.txt, enabled: true}\n"
    )
    (tmp_path / "manual_seeds.txt").write_text(
        "python\nConstruction\nestimators\ndataisbeautiful\n"
        "r/gonewild is on every list, so is reddit.com/r/nsfw\nzz_ghost_zz\n"
    )
    (tmp_path / "force_block.txt").write_text("Borderline_Test\n")
    monkeypatch.setattr(subgate.RedditClient, "get_json", _fake_get_json)

    for _ in range(2):  # second pass proves re-verification is idempotent
        subgate.main(["run"])
        state = subgate.load_state()
        counts = subgate.summarize(state)
        assert counts == {"nsfw": 3, "sfw": 4, "gone": 0}
        assert "zz_ghost_zz" not in state["subs"]
        assert state["subs"]["nsfw"]["name"] == "NSFW"  # canonical casing kept
        full = (tmp_path / subgate.FULL_LIST).read_text().splitlines()
        rules = [ln for ln in full if not ln.startswith("!")]
        assert rules == [
            "||reddit.com/r/gonewild^",
            "||reddit.com/r/NSFW^",
            "||reddit.com/r/FreshSpice^",
            "||reddit.com/r/Borderline_Test^",
        ]
        assert "! Entry count: 4" in full
        chrome = (tmp_path / subgate.CHROME_LIST).read_text().splitlines()
        assert sum(1 for ln in chrome if not ln.startswith("!")) == 3  # cap applied


def test_postpone_graphql_scraper(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"data": {"nsfwSubreddits": [
                {"name": "Spicy_One"}, {"name": "Another2"},
                {"name": "bad name"}, {"name": ""},
            ]}}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["query"] = json["query"]
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr(subgate.requests, "post", fake_post)
    monkeypatch.setattr(subgate.time, "sleep", lambda *a: None)
    got = subgate.scrape_postpone_graphql(
        {"url": "https://example.test/graphql", "limit": 123, "timeout": 60})
    assert got == {"Spicy_One", "Another2"}   # invalid names filtered
    assert "nsfwSubreddits(limit:123)" in captured["query"]
    assert captured["timeout"] == 60


def test_postpone_graphql_raises_on_errors_or_empty(monkeypatch):
    class Resp:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    monkeypatch.setattr(subgate.time, "sleep", lambda *a: None)

    monkeypatch.setattr(subgate.requests, "post",
                        lambda *a, **k: Resp({"errors": [{"message": "nope"}]}))
    try:
        subgate.scrape_postpone_graphql({})
        raise AssertionError("should have raised on graphql errors")
    except RuntimeError:
        pass

    monkeypatch.setattr(subgate.requests, "post",
                        lambda *a, **k: Resp({"data": {"nsfwSubreddits": []}}))
    try:
        subgate.scrape_postpone_graphql({})
        raise AssertionError("should have raised on empty result")
    except RuntimeError:
        pass


def test_scraper_failure_never_shrinks_state(monkeypatch, tmp_path):
    """Guard: a source blowing up must not remove anything from the catalog."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "sources.yaml").write_text(
        "sources:\n  - {name: boom, type: postpone_graphql, enabled: true}\n")
    def boom(src):
        raise RuntimeError("source down")
    monkeypatch.setitem(subgate.SCRAPERS, "postpone_graphql", boom)
    cfg = subgate.load_config("sources.yaml")
    cands = subgate.collect_candidates(cfg, include_directories=True)
    assert cands == {}


def test_is_scrape_time_gates_on_day_and_hour():
    cfg = {"scrape_weekday": 6, "scrape_hour": 9}
    tz = subgate.dt.timezone.utc
    sunday_9 = subgate.dt.datetime(2026, 7, 19, 9, 13, tzinfo=tz)   # Sunday
    sunday_15 = subgate.dt.datetime(2026, 7, 19, 15, 13, tzinfo=tz)
    saturday_9 = subgate.dt.datetime(2026, 7, 18, 9, 13, tzinfo=tz)
    assert subgate.is_scrape_time(cfg, sunday_9) is True
    assert subgate.is_scrape_time(cfg, sunday_15) is False
    assert subgate.is_scrape_time(cfg, saturday_9) is False


def test_no_em_dashes_anywhere():
    """Project rule: no em dashes in any file, ever. This automates the sweep."""
    skip_dirs = {".git", "__pycache__", ".pytest_cache"}
    skip_files = {subgate.STATE_FILE, subgate.FULL_LIST, subgate.CHROME_LIST}
    offenders = []
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fn in filenames:
            if fn in skip_files or fn.endswith((".pyc", ".zip")):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8", errors="ignore") as f:
                    if "\u2014" in f.read():
                        offenders.append(os.path.relpath(p, REPO_ROOT))
            except OSError:
                continue
    assert not offenders, f"em dash found in: {offenders}"
