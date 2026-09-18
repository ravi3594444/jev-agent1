"""Typed question sets, one per stream kind.

Everything a non-programmer needs to tune lives in config.toml; these builders
just turn that config into the Choice / Score / Noul payload Jev expects.

Design rule: ask several small, independent questions in ONE call rather than
one big vague question. Batched questions are cheaper and each answer gets its
own calibrated confidence, which is what the gating depends on.
"""
from __future__ import annotations

from .jev import choice, noul, score

DEFAULT_FIT_LEVELS = [
    "No overlap with what we do",
    "Loosely adjacent, would be a stretch",
    "Partial match, we could cover most of it",
    "Strong match for our core services",
    "Bullseye - exactly the work we want",
]

DEFAULT_LEAD_KINDS = {
    "open_opportunity": "An open tender, RFP, RFQ, or role that can still be responded to",
    "prequalification": "An expression-of-interest or prequalification notice, not the main bid yet",
    "award_notice": "Announces an already-awarded contract or filled role - too late to bid",
    "not_an_opportunity": "General news, commentary, or anything that is not a real listing",
}

DEFAULT_IMPORTANCE_LEVELS = [
    "Noise - chatter, opinion, or a rehash of old news",
    "Minor - small update, narrow audience",
    "Notable - worth knowing about this week",
    "Significant - changes how people build or buy",
    "Major - a landmark release or shift in the field",
]

DEFAULT_TECH_CATEGORIES = {
    "model_release": "A new model, version, or capability released by a lab",
    "tooling": "Developer tools, frameworks, SDKs, infrastructure, APIs",
    "research": "A paper, benchmark, or research result",
    "business": "Funding, acquisitions, pricing, market or company news",
    "security": "Vulnerabilities, incidents, safety or abuse findings",
    "other": "Anything that does not fit the categories above",
}


def _relevance(include: str, exclude: str, subject: str) -> dict:
    return noul(
        f"This item is relevant to us. {subject}",
        true_desc=include,
        false_desc=exclude,
    )


def leads(cfg: dict) -> dict:
    """Question set for tenders, RFPs, contract listings and roles."""
    include = cfg.get("include", "")
    exclude = cfg.get("exclude", "")
    return {
        "relevant": _relevance(
            include,
            exclude,
            "Judge only whether the work described is something we could realistically pursue.",
        ),
        "fit": score(
            "How closely the work described matches our capabilities.",
            cfg.get("fit_levels", DEFAULT_FIT_LEVELS),
        ),
        "kind": choice(
            "What kind of listing this is.",
            cfg.get("kinds", DEFAULT_LEAD_KINDS),
        ),
        "time_sensitive": noul(
            "There is a stated deadline or the item implies action is needed soon.",
            true_desc="A closing date, submission deadline, or explicit urgency is present",
            false_desc="No deadline is mentioned and nothing suggests urgency",
        ),
    }


def tech(cfg: dict) -> dict:
    """Question set for AI / engineering news streams."""
    include = cfg.get("include", "")
    exclude = cfg.get("exclude", "")
    return {
        "relevant": _relevance(
            include,
            exclude,
            "Judge only the subject matter, not the writing quality.",
        ),
        "importance": score(
            "How much this actually matters to someone working in the field.",
            cfg.get("importance_levels", DEFAULT_IMPORTANCE_LEVELS),
        ),
        "category": choice(
            "Which bucket this item belongs in.",
            cfg.get("categories", DEFAULT_TECH_CATEGORIES),
        ),
        "actionable": noul(
            "There is something concrete here we could try, adopt, or act on.",
            true_desc="Names a usable tool, model, technique, or a decision we may need to make",
            false_desc="Purely informational, speculative, or opinion",
        ),
    }


DEFAULT_POSTING_KINDS = {
    "hiring": "Someone needs work done and is looking to pay for it - a client, employer or agency",
    "offering": "Someone is advertising their OWN services or availability - a freelancer touting for work",
    "discussion": "A question, opinion, or general chat about freelancing rather than a real posting",
}

DEFAULT_WORK_KINDS = {
    "web_development": "Websites, web apps, frontend, backend, e-commerce, CMS, WordPress, Shopify",
    "ai_automation": "LLM integration, AI agents, chatbots, RAG, document understanding, prompt work",
    "workflow_automation": "Make.com, n8n, Zapier, Airtable, Retool, API integrations, RPA, "
                           "connecting tools together, scraping and data pipelines",
    "several": "Needs a combination of the above - for example a web app with an AI or automation layer",
    "other": "A discipline we do not cover - design, video, marketing, copywriting, hardware, native mobile",
}

DEFAULT_BUDGET_LEVELS = [
    "No budget or money mentioned at all",
    "Tiny - a few hundred, or a one-off micro task",
    "Small - low thousands, a few weeks of work",
    "Mid - tens of thousands, a real project",
    "Large - a long engagement, retainer, or six figures",
]


def clients(cfg: dict) -> dict:
    """Question set for freelance and contract work leads.

    `posting_kind` does the heavy lifting: boards like r/forhire are roughly half
    people advertising themselves, and a relevance score alone cannot tell the
    difference between "I need a developer" and "I am a developer". A typed
    Choice can, and the gate drops the wrong side outright.
    """
    include = cfg.get("include", "")
    exclude = cfg.get("exclude", "")
    return {
        "relevant": _relevance(
            include,
            exclude,
            "Judge whether this is work we could win and deliver.",
        ),
        "posting_kind": choice(
            "Is this someone LOOKING TO HIRE, or someone advertising themselves?",
            cfg.get("posting_kinds", DEFAULT_POSTING_KINDS),
        ),
        "work_kind": choice(
            "What kind of work does this mainly call for.",
            cfg.get("work_kinds", DEFAULT_WORK_KINDS),
        ),
        "budget": score(
            "How much money this posting implies, judging from any stated rate, "
            "budget, scope or seniority.",
            cfg.get("budget_levels", DEFAULT_BUDGET_LEVELS),
        ),
        "contactable": noul(
            "There is a clear way to respond - a contact detail, an application "
            "link, or an invitation to message.",
            true_desc="Gives an email, form, link, or explicitly asks people to get in touch",
            false_desc="No route to reply, or the posting is already closed or filled",
        ),
    }


SETS = {"leads": leads, "tech": tech, "clients": clients}


def build(question_set: str, cfg: dict) -> dict:
    if question_set not in SETS:
        raise ValueError(f"unknown question_set {question_set!r}; pick one of {sorted(SETS)}")
    return SETS[question_set](cfg)
