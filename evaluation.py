"""Roadmap Phase 10: evaluation of the matching pipeline.

Compares two methods on 10 labeled test ideas (each idea has one known
correct supervisor, matched by surname key so Dr./Ms. prefixes don't matter):
  1. TF-IDF only (baseline)
  2. Full pipeline: TF-IDF + domain boost + capacity/load filter
If USE_BERT=1 and sentence-transformers is installed, a third method
(hybrid 0.4 TF-IDF + 0.6 BERT) is added automatically.

Metrics (single relevant supervisor per idea):
  Hit@3 / Hit@5 - share of ideas whose correct supervisor is in the top 3 / 5
  MRR           - mean reciprocal rank (0 when not in top 5)
  NDCG@5        - ranking quality, ideal rank = 1

Run standalone:  python evaluation.py
Or via the API:  GET /evaluation
"""

import json
import math
import os

try:
    from backend.database import get_supervisors, seed
    from backend.nlp import BERT_MODEL, match_idea
except ImportError:
    from database import get_supervisors, seed
    from nlp import BERT_MODEL, match_idea

TEST_IDEAS = [
    ("AI based financial decision support system",
     "System that helps managers take financial decisions using AI.", "Waseema"),
    ("Smart campus attendance using IoT sensors",
     "Automatic attendance with IoT sensors installed in classrooms.", "Wagan"),
    ("Federated learning for network intrusion detection",
     "Detect network attacks while keeping data private with federated learning.", "Reehan"),
    ("Online admission portal website for university",
     "A website where students apply for admission and track their application.", "Shahid"),
    ("Android attendance app for students",
     "Mobile app for teachers to mark student attendance on Android phones.", "Umair"),
    ("Data science dashboard for exam results analysis",
     "Dashboard that analyses exam results and shows trends with data science.", "Mustafa"),
    ("Deep learning Roman Urdu chatbot using NLP",
     "Chatbot that understands Roman Urdu questions using NLP and deep learning.", "Mustafa"),
    ("Secure online voting system with blockchain",
     "Online voting platform secured with cybersecurity and blockchain.", "Ayaz"),
    ("Campus network security monitoring tool",
     "Tool that monitors the campus computer network for security threats.", "Mairaj"),
    ("Machine learning model to predict student grades",
     "Predict student grades from past performance using machine learning.", "Mustafa"),
]


def _metrics(ranks, k=5):
    """ranks: list of 1-based ranks (None = not found in top-k)."""
    hits3 = sum(1 for r in ranks if r is not None and r <= 3)
    hits5 = sum(1 for r in ranks if r is not None and r <= 5)
    mrr = sum((1.0 / r) if r is not None else 0.0 for r in ranks) / len(ranks)
    ndcg = sum(
        (1.0 / math.log2(r + 1)) if r is not None else 0.0 for r in ranks
    ) / len(ranks)
    return {
        "Hit@3": round(hits3 / len(ranks), 3),
        "Hit@5": round(hits5 / len(ranks), 3),
        "MRR": round(mrr, 3),
        "NDCG@5": round(ndcg, 3),
    }


def run_evaluation():
    seed()
    supervisors = get_supervisors()
    methods = {
        "TF-IDF only": dict(use_domain_boost=False, use_capacity_filter=False,
                            use_verified_boost=False, use_bert=False),
        "Full pipeline (TF-IDF + domain boost + capacity)": dict(
            use_domain_boost=True, use_capacity_filter=True,
            use_verified_boost=True, use_bert=False
        ),
    }
    if BERT_MODEL is not None:
        methods["Hybrid (0.4 TF-IDF + 0.6 BERT)"] = dict(
            use_domain_boost=True, use_capacity_filter=True,
            use_verified_boost=True, use_bert=True
        )
    else:
        # v5: if BERT was measured once on a machine with the model
        # installed, show those numbers as a reference (clearly labelled
        # in the response) instead of hiding the third method entirely.
        cache = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "backend", "bert_evaluation.json")
        if os.path.exists(cache):
            try:
                with open(cache, encoding="utf-8") as f:
                    cached = json.load(f)
                # Only add methods the live run does not compute itself
                # (the BERT hybrid row); the TF-IDF and full-pipeline rows
                # are always measured live, never taken from the cache.
                for name, metrics in cached.get("methods", {}).items():
                    if name not in methods:
                        methods[name] = None  # marker: results come from cache
                cached_results = cached.get("methods", {})
            except Exception:
                cached_results = {}
        else:
            cached_results = {}
    results, per_idea = {}, []
    for name, kwargs in methods.items():
        if kwargs is None:  # cached BERT results (see above)
            results[name] = cached_results[name]
            continue
        ranks = []
        for title, desc, expected_key in TEST_IDEAS:
            matches, _ = match_idea(f"{title} {desc}", supervisors, top_n=5, **kwargs)
            rank = next(
                (i + 1 for i, m in enumerate(matches) if expected_key in m["name"]),
                None,
            )
            ranks.append(rank)
        results[name] = _metrics(ranks)
        if name == "Full pipeline (TF-IDF + domain boost + capacity)":
            per_idea = [
                {
                    "idea": title,
                    "expected_supervisor_contains": key,
                    "full_pipeline_rank": rank,
                }
                for (title, _, key), rank in zip(TEST_IDEAS, ranks)
            ]
    return {
        "test_ideas": len(TEST_IDEAS),
        "bert_available": BERT_MODEL is not None,
        "bert_cached": (BERT_MODEL is None and bool(cached_results)) if 'cached_results' in locals() else False,
        "methods": results,
        "per_idea": per_idea,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_evaluation(), indent=2))
