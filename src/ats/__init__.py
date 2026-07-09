"""ATS adapters. One module per platform. detector.py routes to the right one.

Tier-1 (deterministic Playwright): greenhouse, lever, ashby, workable, smartrecruiters.
Tier-2 (browser-use + Gemini): llm_fallback for everything else (Workday, iCIMS, custom).
"""
