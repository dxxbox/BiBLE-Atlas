from __future__ import annotations


def build_search_profile() -> dict:
    return {
        "tag": "memory",
        "search_type_profile": {
            "keyword": {
                "enabled": True,
                "term_fields": [
                    {"field": "memory_id.keyword", "weight": 5.0},
                    {"field": "task_ids.keyword", "weight": 2.0},
                    {"field": "feature_tags.keyword", "weight": 1.5},
                    {"field": "domain_tags.keyword", "weight": 1.2},
                    {"field": "component_tags.keyword", "weight": 1.2},
                ],
            },
            "title": {
                "enabled": True,
                "match_fields": [
                    {"field": "title", "weight": 3.0},
                ],
            },
            "text": {
                "enabled": True,
                "multi_match_type": "most_fields",
                "fields": [
                    {"field": "title", "weight": 3.0},
                    {"field": "abstract", "weight": 3.0},
                    {"field": "overview", "weight": 2.5},
                    {"field": "content", "weight": 2.0},
                ],
            },
            "vector": {
                "enabled": True,
                "vector_field": "content_vector",
                # abstract + overview 整体向量化，不分块
                "source_template": "{title}\n{abstract}\n{overview}",
                "num_candidates_min": 100,
                "num_candidates_multiplier": 3,
            },
            "hybrid": {
                "enabled": True,
                "default_vector_weight": 0.65,
            },
        },
        "response_fields": [
            "doc_id",
            "memory_id",
            "title",
            "abstract",
            "overview",
            "task_ids",
            "feature_tags",
            "domain_tags",
            "component_tags",
            "metadata.related_storage_paths",
            "score",
        ],
    }
