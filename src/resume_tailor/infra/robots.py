"""robots.txt rules for one host (RFC 9309), parsed here rather than by `urllib.robotparser`.

The standard library applies the first matching rule in file order and treats ``*`` and
``$`` literally. RFC 9309 instead takes the longest matching rule, and a tie goes to
Allow. This parser is stricter than that on a tie: Disallow wins, so a rule pair a site
wrote ambiguously keeps us out.

The group whose user agent names ResumeTailor applies when there is one; otherwise the
``*`` group does. Groups for the same agent are merged. Pure, no network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The product token we match against ``User-agent`` lines.
AGENT = "resumetailor"


@dataclass(frozen=True)
class Rules:
    """The Allow and Disallow patterns that apply to us on one host."""

    allow: tuple[str, ...] = ()
    disallow: tuple[str, ...] = ()

    def allows(self, path: str) -> bool:
        """Whether ``path`` (with its query) may be fetched."""
        if path.split("?")[0] == "/robots.txt":
            return True
        best_allow = max((len(p) for p in self.allow if _matches(p, path)), default=-1)
        best_disallow = max((len(p) for p in self.disallow if _matches(p, path)), default=-1)
        return best_disallow < 0 or best_allow > best_disallow


#: Everything allowed: a robots.txt that does not exist.
ALLOW_ALL = Rules()
#: Nothing allowed: a robots.txt that could not be read.
DISALLOW_ALL = Rules(disallow=("/",))


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = re.escape(pattern[:-1] if anchored else pattern).replace(r"\*", ".*")
    return re.match(body + ("$" if anchored else ""), path) is not None


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    allow: list[str] = field(default_factory=list)
    disallow: list[str] = field(default_factory=list)


def _groups(text: str) -> list[_Group]:
    groups: list[_Group] = []
    current: _Group | None = None
    in_agents = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        key = key.lower()
        if key == "user-agent":
            if current is None or not in_agents:
                current = _Group()
                groups.append(current)
            current.agents.append(value.lower())
            in_agents = True
        elif key in ("allow", "disallow") and current is not None:
            in_agents = False
            if value:  # an empty Disallow disallows nothing
                (current.allow if key == "allow" else current.disallow).append(value)
        else:
            in_agents = False
    return groups


def parse(text: str) -> Rules:
    """The rules ``text`` sets for ResumeTailor."""
    groups = _groups(text)
    ours = [g for g in groups if any(a.split("/")[0].strip() == AGENT for a in g.agents)]
    chosen = ours or [g for g in groups if "*" in g.agents]
    return Rules(
        allow=tuple(p for g in chosen for p in g.allow),
        disallow=tuple(p for g in chosen for p in g.disallow),
    )
