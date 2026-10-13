"""Shared skills lexicon (lower-case, word-bounded matching).

Two consumers with different needs:

  - src/resume/validator.py uses TECH_SKILLS to catch fabricated tools even
    when the model writes them in lower case ("pytorch", "kubernetes") —
    the capitalised-token check alone can't see those.
  - src/discovery/fit.py uses ALL_SKILLS to find which skills a JD asks for.

Rules for entries: lower case, unambiguous in ordinary prose. No "go", "r",
"c", "swift", "rest", "spring", "rails", "lambda" — they are English words
too and would cause false positives. Use the multi-word forms instead.
"""

from __future__ import annotations

import re

TECH_SKILLS: frozenset[str] = frozenset({
    # languages
    "python", "java", "javascript", "typescript", "golang", "rust", "c++", "c#", "scala",
    "kotlin", "ruby", "php", "sql", "bash", "elixir", "haskell", "matlab", "julia",
    "swiftui", "objective-c", "perl", "lua", "dart", "clojure", "f#", "solidity",
    # web / backend
    "reactjs", "react.js", "next.js", "vue", "angular", "svelte", "node.js", "django", "flask", "fastapi",
    "spring boot", "ruby on rails", "graphql", "rest api", "restful", "grpc", "tailwind",
    "redux", "express.js", ".net", "asp.net", "laravel", "webpack", "vite",
    # data / ml
    "pytorch", "tensorflow", "jax", "keras", "scikit-learn", "pandas", "numpy", "spark",
    "pyspark", "hadoop", "airflow", "dbt", "kafka", "flink", "snowflake", "databricks",
    "bigquery", "redshift", "tableau", "looker", "power bi", "langchain", "llamaindex",
    "hugging face", "huggingface", "xgboost", "lightgbm", "mlflow", "kubeflow", "sagemaker",
    "vertex ai", "openai", "pgvector", "pinecone", "weaviate", "chroma", "faiss",
    "dask", "polars", "duckdb", "opencv", "spacy", "nltk",
    # infra / cloud
    "aws", "gcp", "azure", "kubernetes", "k8s", "docker", "terraform", "ansible",
    "github actions", "gitlab ci", "jenkins", "circleci", "argocd", "prometheus", "grafana",
    "datadog", "splunk", "new relic", "opentelemetry", "aws lambda", "cloudformation",
    "pulumi", "nginx", "istio", "consul", "postgresql", "postgres",
    "mysql", "mongodb", "redis", "elasticsearch", "opensearch", "dynamodb", "cassandra",
    "sqlite", "clickhouse", "cockroachdb", "rabbitmq", "celery",
    # mobile
    "ios", "android", "react native", "flutter", "xcode",
    # certifications / methods with proper names
    "pmp", "cissp", "cka", "ckad", "six sigma", "itil", "togaf",
})

PRACTICE_SKILLS: frozenset[str] = frozenset({
    "machine learning", "deep learning", "nlp", "computer vision", "llm", "llms", "rag",
    "fine-tuning", "transformers", "vector database", "embeddings", "mlops",
    "feature store", "a/b testing", "statistics", "recommendation systems",
    "reinforcement learning", "generative ai", "prompt engineering", "evals",
    "linux", "ci/cd", "observability", "microservices", "distributed systems",
    "serverless", "networking", "security", "oauth", "sre", "devops",
    "agile", "scrum", "kanban", "roadmap", "stakeholder management", "mentoring",
    "hiring", "people management", "product management", "system design",
    "cross-functional", "okrs", "budget", "vendor management", "compliance",
    "data governance", "privacy", "accessibility", "tdd", "code review",
})

# Too ambiguous for the validator (English words), but useful JD signals.
FIT_ONLY_SKILLS: frozenset[str] = frozenset({"react", "helm", "spring", "rails"})

ALL_SKILLS: frozenset[str] = TECH_SKILLS | PRACTICE_SKILLS | FIT_ONLY_SKILLS


def term_regex(term: str) -> re.Pattern[str]:
    """Word-bounded, case-insensitive matcher that tolerates symbols (c++, ci/cd, .net)."""
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9+#])", re.IGNORECASE)


_COMPILED: dict[str, re.Pattern[str]] = {}


def contains_term(text: str, term: str) -> bool:
    rx = _COMPILED.get(term)
    if rx is None:
        rx = _COMPILED[term] = term_regex(term)
    return rx.search(text) is not None


def find_terms(text: str, terms: frozenset[str]) -> dict[str, int]:
    """{term: first index} for every lexicon term present in `text`."""
    out: dict[str, int] = {}
    for t in terms:
        rx = _COMPILED.get(t)
        if rx is None:
            rx = _COMPILED[t] = term_regex(t)
        m = rx.search(text)
        if m:
            out[t] = m.start()
    return out
