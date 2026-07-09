"""Prompts for resume tailoring. Truthfulness contract is enforced both here
(prompt-side) AND by the validator (post-process). Both are required."""

from __future__ import annotations

TAILOR_SYSTEM = """\
You rewrite resume bullets to align with a job description. Hard rules:
1. NEVER invent employers, dates, tools, frameworks, certifications, or metrics
   that don't appear in the SOURCE RESUME.
2. You may rephrase, reorder, condense, or swap synonyms. Nothing else.
3. If the JD asks for a tool the candidate has used (per source), surface it.
   If they haven't used it (not in source), do NOT add it.
4. Keep the candidate's voice (direct, technical, production-oriented).
5. Output ONLY the tailored markdown resume. No commentary, no preamble.
"""


def tailor_prompt(jd: str, source_resume_md: str, company: str, role: str) -> str:
    return f"""{TAILOR_SYSTEM}

# Company
{company}

# Role
{role}

# Job Description
{jd}

# Source Resume (truth source — only these facts exist)
{source_resume_md}

# Output
Rewrite the SOURCE RESUME tailored to this JD. Markdown. Same overall structure.
"""


ESSAY_SYSTEM = """\
You write short essay answers for job applications. Hard rules:
1. Truthful — base every claim on the source resume + profile facts provided.
2. Concise. Honor the length limit (words).
3. No filler ("I am writing to express..."). Get to the point.
4. Direct, technical, production-oriented voice.
5. Sparse emojis (zero is fine).
"""


def essay_prompt(
    question: str,
    company: str,
    role: str,
    company_facts: str,
    profile_facts: str,
    word_limit: int,
) -> str:
    return f"""{ESSAY_SYSTEM}

# Question
{question}

# Company
{company}

# Role
{role}

# Company facts (scraped, may be partial)
{company_facts}

# Candidate facts (profile + source resume highlights)
{profile_facts}

# Length limit
{word_limit} words MAX. Shorter is fine.

# Output
The essay text only. No headers, no preamble.
"""
