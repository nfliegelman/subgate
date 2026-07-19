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
    assert subgate.rule_line("Some_Sub") == "||reddit.com/r/Some_Sub^$all"


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
    net = [ln for ln in lines if ln.startswith("||")]
    assert net == ["||reddit.com/r/A^$all", "||reddit.com/r/B^$all"]
    assert "reddit.com##shreddit-post[nsfw]" in lines  # feed hygiene ships


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
        "verification: {provider: reddit}\n"
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
    monkeypatch.setattr(subgate.RedditClient, "_authenticate", lambda self: None)
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test")

    for _ in range(2):  # second pass proves re-verification is idempotent
        subgate.main(["run"])
        state = subgate.load_state()
        counts = subgate.summarize(state)
        assert counts == {"nsfw": 3, "sfw": 4, "gone": 0}
        assert "zz_ghost_zz" not in state["subs"]
        assert state["subs"]["nsfw"]["name"] == "NSFW"  # canonical casing kept
        full = (tmp_path / subgate.FULL_LIST).read_text().splitlines()
        rules = [ln for ln in full if ln.startswith("||")]
        assert rules == [
            "||reddit.com/r/gonewild^$all",
            "||reddit.com/r/NSFW^$all",
            "||reddit.com/r/FreshSpice^$all",
            "||reddit.com/r/Borderline_Test^$all",
        ]
        assert "! Entry count: 4" in full
        chrome = (tmp_path / subgate.CHROME_LIST).read_text().splitlines()
        assert sum(1 for ln in chrome if ln.startswith("||")) == 3  # cap applied


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


# ---------------------------------------------------------------------------
# Postpone verification path (no Reddit credentials)
# ---------------------------------------------------------------------------

class FakePostpone:
    """Stands in for PostponeVerifier without touching the network."""

    name = "postpone"

    def __init__(self, bulk, lookups, budget=300):
        self._bulk = bulk
        self._lookups = lookups
        self.lookup_budget = budget
        self.calls = 0
        self.looked_up = []

    def bulk_nsfw(self):
        self.calls += 1
        return dict(self._bulk)

    def lookup(self, name):
        self.calls += 1
        self.looked_up.append(name)
        return self._lookups.get(name)


def test_postpone_bulk_marks_nsfw_and_absence_never_marks_sfw():
    """Core guard: the bulk list is capped, so absence means unknown, not safe."""
    state = fresh_state()
    now = "2026-07-18T00:00:00Z"
    bulk = {"gonewild": {"name": "gonewild", "over18": True,
                         "subscribers": 100, "type": None}}
    v = FakePostpone(bulk, lookups={}, budget=0)   # budget 0 disables the drain
    state["subs"]["someothersub"] = {
        "name": "SomeOtherSub", "over18": True, "subscribers": 5, "status": "nsfw",
        "sources": [], "misses": 0, "first_seen_utc": now, "last_verified_utc": now,
    }
    subgate.verify_via_postpone(v, state, {"someothersub"}, 3, now)
    assert state["subs"]["gonewild"]["status"] == "nsfw"
    # Present in the catalog, absent from bulk, not looked up: must be untouched.
    assert state["subs"]["someothersub"]["status"] == "nsfw"
    assert state["subs"]["someothersub"]["misses"] == 0


def test_postpone_drain_respects_budget_and_sets_status():
    state = fresh_state()
    now = "2026-07-18T00:00:00Z"
    lookups = {
        "safeone": {"name": "SafeOne", "over18": False, "subscribers": 9, "type": "public"},
        "spicyone": {"name": "SpicyOne", "over18": True, "subscribers": 7, "type": "public"},
        "ghostone": None,
    }
    v = FakePostpone(bulk={}, lookups=lookups, budget=2)
    subgate.verify_via_postpone(v, state, set(lookups.keys()), 3, now)
    assert len(v.looked_up) == 2                      # budget honored
    for key in v.looked_up:
        if lookups[key] is None:
            assert key not in state["subs"]           # unknown name stays unknown
        else:
            expected = "nsfw" if lookups[key]["over18"] else "sfw"
            assert state["subs"][key]["status"] == expected


def test_postpone_lookup_failure_does_not_abort_drain(capsys):
    state = fresh_state()
    now = "2026-07-18T00:00:00Z"

    class Flaky(FakePostpone):
        def lookup(self, name):
            self.calls += 1
            self.looked_up.append(name)
            if name == "boom":
                raise RuntimeError("transient")
            return {"name": name, "over18": True, "subscribers": 1, "type": "public"}

    v = Flaky(bulk={}, lookups={}, budget=5)
    subgate.verify_via_postpone(v, state, {"boom", "aaa", "bbb"}, 3, now)
    assert len(v.looked_up) == 3                      # kept going past the failure
    assert state["subs"]["aaa"]["status"] == "nsfw"
    assert "boom" not in state["subs"]


def test_build_verifier_picks_postpone_without_credentials(monkeypatch):
    monkeypatch.delenv("REDDIT_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDDIT_CLIENT_SECRET", raising=False)
    v, is_reddit = subgate.build_verifier({"verification": {"provider": "auto"}})
    assert is_reddit is False
    assert v.name == "postpone"


def test_build_verifier_prefers_reddit_when_credentials_exist(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "x")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "y")
    monkeypatch.setattr(subgate.RedditClient, "_authenticate", lambda self: None)
    v, is_reddit = subgate.build_verifier({"verification": {"provider": "auto"}})
    assert is_reddit is True


def test_userscript_is_present_and_well_formed():
    path = os.path.join(REPO_ROOT, "subgate.user.js")
    src = open(path, encoding="utf-8").read()
    assert "// ==UserScript==" in src and "// ==/UserScript==" in src
    assert f"@version      {subgate.VERSION}" in src, "userscript version must track VERSION"
    assert src.count("(") == src.count(")")
    assert src.count("{") == src.count("}")
    # v0.3.0 architecture: data layers first, markup demoted to tiebreaker.
    for needed in ("@grant        GM_xmlhttpRequest",
                   "@connect      raw.githubusercontent.com",
                   "@connect      api.postpone.app",
                   "your subgate list",
                   "isNsfwSubreddit"):
        assert needed in src, f"userscript missing: {needed}"


def test_setup_scripts_never_handle_tokens():
    """Guard: setup must route auth through the owner's browser, never a token."""
    for fn in ("setup.sh", "setup.ps1"):
        src = open(os.path.join(REPO_ROOT, fn), encoding="utf-8").read()
        assert "gh auth login" in src, f"{fn} must use the browser login flow"
        lowered = src.lower()
        for banned in ("github_pat_", "ghp_", "read-host", "with_token", "gh auth login --with-token"):
            assert banned not in lowered, f"{fn} must not touch tokens ({banned})"


def test_userscript_version_tracks_module_version():
    src = open(os.path.join(REPO_ROOT, "subgate.user.js"), encoding="utf-8").read()
    assert f"@version      {subgate.VERSION}" in src


def test_extension_manifest_and_scripts():
    ext = os.path.join(REPO_ROOT, "extension")
    with open(os.path.join(ext, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    assert m["manifest_version"] == 3
    assert m["version"] == subgate.VERSION, "manifest version must track VERSION"
    assert "declarativeNetRequest" in m["permissions"]
    assert "webNavigation" in m["permissions"]
    hosts = " ".join(m["host_permissions"])
    for needed in ("reddit.com", "raw.githubusercontent.com", "api.postpone.app"):
        assert needed in hosts
    for fn in ("background.js", "content.js", "blocked.js", "options.js"):
        src = open(os.path.join(ext, fn), encoding="utf-8").read()
        assert src.count("(") == src.count(")"), fn
        assert src.count("{") == src.count("}"), fn
    bg = open(os.path.join(ext, "background.js"), encoding="utf-8").read()
    assert "OWNER/subgate" in bg, "placeholder must ship; the workflow personalizes it"


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
