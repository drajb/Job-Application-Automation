"""Resume pipeline: selector → tailor → validator → renderer.

Reads from `RESUME_SOURCE_DIR` (default `./resumes/`, READ-ONLY). All outputs land in
apply-agent/data/tailored/<uuid>.pdf with UUID stamped into PDF metadata.
Master .docx files are NEVER modified.
"""
