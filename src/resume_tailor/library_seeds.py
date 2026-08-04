"""Built-in vocabulary packs: the tag-alias and verb-family tables shipped in code.

Pure data, zero imports — `config.py` initialises `TAG_ALIASES` / `VERB_FAMILIES` from
`BUILTIN_PACKS["core-tech"]` at import time, and `libraries.py` unions these into the
same registry as any user-authored pack under `data/libraries/packs/`. Kept as Python
constants rather than a JSON file under `src/` so a built-in pack costs zero I/O to read
and needs no packaging entry — `data/` is gitignored and never copied into the Docker
image, so a seed cannot live there.

Every value here must already satisfy the invariants `libraries.validate_pack` enforces
on a user pack: alias values are fixed points of the alias table (no `a -> b -> c`
chains), and a verb appears in exactly one family within a pack. `tests/test_config.py`
and `tests/test_libraries.py` pin both for this pack specifically.
"""

from __future__ import annotations

from typing import TypedDict


class Pack(TypedDict):
    id: str
    label: str
    description: str
    tag_aliases: dict[str, str]
    verb_families: dict[str, tuple[str, ...]]


#: The original single-industry tables, unchanged, as the always-available default pack.
#: Every user starts with this enabled and nothing else — moving it here changes no
#: behaviour by itself (see `config.py`'s init from `BUILTIN_PACKS["core-tech"]`).
_CORE_TECH: Pack = {
    "id": "core-tech",
    "label": "Software & Data",
    "description": (
        "Programming languages, web/cloud/ML tooling, and retrieval/LLM vocabulary."
    ),
    "tag_aliases": {
        "py": "python",
        "py3": "python",
        "python3": "python",
        "js": "javascript",
        "ts": "typescript",
        "node": "nodejs",
        "node.js": "nodejs",
        "postgres": "postgresql",
        "k8s": "kubernetes",
        "ml": "machine learning",
        "nlp": "natural language processing",
        "ci/cd": "cicd",
        "ci / cd": "cicd",
        "rest api": "rest",
        "restful": "rest",
        # Retrieval/LLM vocabulary. A posting and a resume rarely spell these the same way,
        # and every miss here costs a relevant bullet its score.
        "retrieval-augmented generation": "rag",
        "retrieval augmented generation": "rag",
        "large language model": "llm",
        "large language models": "llm",
        "llms": "llm",
        "vector databases": "vector database",
        "vector store": "vector database",
        "vector search": "semantic search",
        "hybrid search": "hybrid retrieval",
        "dense retrieval": "embeddings",
        "dense embeddings": "embeddings",
        "keyword matching": "information retrieval",
        "keyword search": "information retrieval",
        "reranker": "reranking",
        "rerankers": "reranking",
        "reranker tuning": "reranking",
        "re-ranking": "reranking",
        "cross-encoder": "reranking",
        "llm as judge": "llm-as-judge",
        "llm-as-judge evaluation": "llm-as-judge",
        "latency optimization": "performance",
        "performance measurement": "performance",
        "model fine-tuning": "fine-tuning",
        "recall@k": "retrieval eval",
        "mrr": "retrieval eval",
        "offline evaluation": "evaluation",
        "fine tuning": "fine-tuning",
        "finetuning": "fine-tuning",
        "rl": "reinforcement learning",
        "full-stack": "full stack",
        "fullstack": "full stack",
    },
    "verb_families": {
        "build": (
            "architected", "assembled", "built", "composed", "constructed", "created",
            "crafted", "designed", "developed", "engineered", "established", "founded",
            "implemented", "initiated", "launched", "modelled", "modeled", "prototyped",
            "shipped", "spearheaded",
        ),
        "improve": (
            "accelerated", "boosted", "condensed", "cut", "enhanced", "expanded", "improved",
            "increased", "optimised", "optimized", "reduced", "refactored", "refined",
            "scaled", "simplified", "streamlined", "strengthened", "tightened", "tuned",
        ),
        "lead": (
            "coordinated", "directed", "facilitated", "guided", "led", "managed", "mentored",
            "onboarded", "organised", "organized", "oversaw", "partnered", "supervised",
            "trained",
        ),
        "analyse": (
            "analysed", "analyzed", "assessed", "audited", "benchmarked", "debugged",
            "diagnosed", "evaluated", "examined", "identified", "investigated", "measured",
            "profiled", "researched", "reviewed", "selected", "tested", "troubleshooted",
            "validated",
        ),
        "write": (
            "authored", "communicated", "documented", "drafted", "presented", "published",
            "reported", "summarised", "summarized", "wrote",
        ),
        "operate": (
            "addressed", "administered", "automated", "configured", "delivered", "deployed",
            "enabled", "handled", "integrated", "maintained", "migrated", "monitored",
            "operated", "processed", "provisioned", "resolved", "secured", "supported",
        ),
    },
}

#: Grounded in one real early-career finance/consulting resume (nonprofit fundraising,
#: a Deloitte mentorship program, an internal-audit internship), not invented from
#: general knowledge alone — every alias and verb below is either the resume's own
#: wording or a spelling/synonym a posting in this field would plausibly use for it.
#:
#: The alias table closes a measured gap on that resume: "Google Workspace", "MS
#: Office", and "KPIs" — all plausible posting spellings — matched none of its own
#: tag/skill wording ("Google Drive Suite", "Microsoft 365", "KPI") before this pack
#: existed. The verb families are forward-looking rather than a fix for anything
#: already broken on that resume: `collaborated` and `received` each open two of its
#: bullets, but `rewrite.verb_collisions`'s exact-duplicate rule already catches an
#: identical repeated word with no family table involved (see
#: `tests/test_library_seeds.py`) — what these families add is coverage for the
#: *near-synonym* rule (three-plus related-but-different openers, e.g. a rewrite that
#: lands on "recruited" for one bullet and "sourced" for another), which `core-tech`
#: cannot see for any of these verbs today.
_FINANCE_CONSULTING: Pack = {
    "id": "finance-consulting",
    "label": "Finance & Consulting",
    "description": (
        "Financial analysis, audit, and client-consulting vocabulary, plus the "
        "fundraising/outreach terms common in early-career finance and "
        "nonprofit-adjacent work."
    ),
    "tag_aliases": {
        # Tooling: the resume's own "Skills" wording is the canonical spelling;
        # postings commonly use the vendor's current or prior product name instead.
        "google workspace": "google drive suite",
        "g suite": "google drive suite",
        "ms office": "microsoft 365",
        "office 365": "microsoft 365",
        "ms 365": "microsoft 365",
        "financial modelling": "financial modeling",
        # "Received exposure to financial analysis, forecasting, and client-ready
        # deliverables" and "...using data-driven performance metrics like risks,
        # efficiency, and KPIs" are both verbatim from the resume's own bullets.
        "kpis": "kpi",
        "key performance indicators": "kpi",
        "key performance indicator": "kpi",
        "internal auditing": "internal audit",
        "budget management": "budgeting",
        "budget planning": "budgeting",
    },
    "verb_families": {
        # "Collaborated with peers and Deloitte consultants..." and "Collaborated on
        # the planning and execution..." — both from the resume; a peer-level joint-work
        # claim, distinct from `core-tech`'s "lead" family, which is about directing.
        "collaborate": ("collaborated", "consulted", "liaised"),
        # "Recruited ~20 volunteers..." — talent/volunteer acquisition, not covered by
        # `core-tech`'s "lead" (onboarded/trained come after recruiting, not instead of it).
        "recruit": ("recruited", "sourced", "enlisted"),
        # "Received exposure to..." (x2) and "Received a trial implementation..." — a
        # passive acquire-experience/credential claim, worth catching if repeated even
        # though it is not a strong resume verb on its own.
        "gained": ("received", "gained", "earned", "obtained"),
        # "Tracked the logistics of purchased goods..." plus "reconciled", the standard
        # finance-register verb for the invoice/contract-matching work the same
        # internship's other bullets describe ("Analyzed purchasing documentation,
        # including contracts and invoices...") — inferred from that context, not a
        # literal word in the resume, unlike every other verb in this pack.
        "track": ("tracked", "logged", "reconciled"),
        # "Promoted the event through various channels..." — outreach/marketing, not
        # `core-tech`'s "write" (drafting content) or "lead" (directing people).
        "promote": ("promoted", "publicized", "marketed"),
    },
}

#: Every built-in pack, keyed by id. `libraries.list_packs()` unions this with the
#: user-authored packs on disk; `libraries.read_pack` checks here first. All disabled
#: by default in a fresh workspace's `libraries.json` (only "core-tech" is enabled),
#: so adding an entry here never changes existing behaviour until a user opts in.
BUILTIN_PACKS: dict[str, Pack] = {
    "core-tech": _CORE_TECH,
    "finance-consulting": _FINANCE_CONSULTING,
}
