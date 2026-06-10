"""Search profile builder — stdlib only (runs inside sandbox subprocess)."""
from __future__ import annotations


def build_search_profile(skill_doc: dict) -> dict:
    """Build SKILL search profile (fixed rules per design doc §5).

    The profile is stored verbatim in the IndexBinding and consumed by
    SkillSearcher._adapt_skill_profile() at search time.

    Layout (flat format, adapted to QueryProfileCompiler by the searcher):
    {
        "keyword": {"fields": ["name.keyword^5"]},
        "title":   {"fields": ["name^3"]},
        "text":    {"fields": ["name^4", "description^2", "body^1.5", "content^1"]},
        "vector":  {
            "vector_field":    "content_vector",
            "source_template": "{name}\\n{description}\\n{body}",
            "num_candidates":  100
        },
        "hybrid":  {"default_vector_weight": 0.5},
        "response_fields": [
            "doc_id", "name", "description",
            "metadata.related_storage_paths", "score"
        ]
    }
    """
    return {
        "keyword": {"fields": ["name.keyword^5"]},
        "title": {"fields": ["name^3"]},
        "text": {"fields": ["name^4", "description^2", "body^1.5", "content^1"]},
        "vector": {
            "vector_field": "content_vector",
            "source_template": "{name}\n{description}\n{body}",
            "num_candidates": 100,
        },
        "hybrid": {"default_vector_weight": 0.5},
        "response_fields": [
            "doc_id",
            "name",
            "description",
            "metadata.related_storage_paths",
            "score",
        ],
    }
