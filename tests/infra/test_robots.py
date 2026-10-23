"""robots.txt rules (`infra/robots.py`): our group or ``*``, longest match, tie to Disallow."""

from __future__ import annotations

from resume_tailor.infra import robots


def test_the_longest_match_wins_and_a_tie_goes_to_disallow():
    rules = robots.parse(
        "User-agent: *\nDisallow: /careers\nAllow: /careers/about\n"
        "Allow: /tie\nDisallow: /tie\n"
    )
    assert not rules.allows("/careers/jobs")
    assert rules.allows("/careers/about-us")
    assert not rules.allows("/tie/page")
    assert rules.allows("/news")


def test_wildcards_and_end_anchors():
    rules = robots.parse("User-agent: *\nDisallow: /*.pdf$\nDisallow: /private*/x\n")
    assert not rules.allows("/files/report.pdf")
    assert rules.allows("/files/report.pdf?download=1")
    assert not rules.allows("/private-area/x")
    assert rules.allows("/public/x")


def test_our_group_replaces_the_star_group_and_groups_for_us_merge():
    text = (
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: Googlebot\nUser-agent: ResumeTailor/1.0\nDisallow: /search\n\n"
        "User-agent: resumetailor\nDisallow: /cart\n"
    )
    rules = robots.parse(text)
    assert rules.allows("/about")
    assert not rules.allows("/search?q=x")
    assert not rules.allows("/cart")


def test_other_agents_and_empty_disallow_do_not_block_us():
    rules = robots.parse("User-agent: BadBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
    assert rules.allows("/anything")
    assert robots.parse("").allows("/")
    assert robots.parse("Disallow: /\n").allows("/")  # a rule outside any group


def test_robots_txt_itself_is_always_readable():
    assert robots.DISALLOW_ALL.allows("/robots.txt")
    assert not robots.DISALLOW_ALL.allows("/")
