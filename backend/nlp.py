"""SupervisorMatch NLP matching engine (full-stack version).

Pipeline (roadmap Phase 6, adapted for a laptop):
1. Preprocessing: lowercase + TF-IDF with English + domain stopwords,
   plus light stemming so "network" matches "networks".
2. Hybrid scoring: TF-IDF cosine (always) + Sentence-BERT semantic
   similarity (only when USE_BERT=1 and sentence-transformers is installed;
   otherwise the TF-IDF score is used on its own and the method is reported).
3. Domain classification by keyword mapping; a domain match adds a +10% boost.
   Verified (Real) faculty profiles whose interests match the idea's domain
   get a further +10% trust boost over the labelled synthetic sample rows.
4. Availability filter: supervisors whose current_load >= capacity are skipped;
   remaining scores are adjusted down as load grows:
   score *= (1 - current_load / capacity * 0.2).
5. Explanations: the top overlapping keywords, strongest TF-IDF weight first.
6. v5 helpers: gibberish detection, idea quality scoring and uniqueness
   check against a sample archive of past FYP titles.
"""

import csv
import os
import re

from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

DOMAIN_STOPWORDS = {
    "project", "final", "year", "based", "using", "system", "systems",
    "development", "application", "applications", "student", "students",
}
STOPWORDS = sorted(set(ENGLISH_STOP_WORDS) | DOMAIN_STOPWORDS)

DOMAIN_KEYWORDS = {
    "Artificial Intelligence & ML": {
        "machine learning", "artificial intelligence", "deep learning", "neural",
        "nlp", "natural language processing", "computer vision", "data mining",
        "ai", "ml", "chatbot", "prediction",
    },
    "Cybersecurity": {
        "cybersecurity", "security", "cryptography", "intrusion", "malware",
        "network security", "vulnerability", "penetration", "hacking", "secure",
    },
    "Blockchain": {
        "blockchain", "smart contract", "cryptocurrency", "distributed ledger",
        "bitcoin", "ethereum", "decentralized",
    },
    "Web Development": {
        "web", "website", "frontend", "backend", "javascript", "react",
        "html", "css", "web application",
    },
    "Mobile App Development": {
        "app", "android", "mobile", "ios", "flutter", "application development",
    },
    "IoT & Robotics": {
        "iot", "internet of things", "robotics", "embedded", "sensor", "smart",
        "arduino", "automation",
    },
    "Data Science": {
        "data science", "big data", "analytics", "visualization", "statistics",
        "dashboard", "data analysis",
    },
    "Software Engineering": {
        "software engineering", "software", "agile", "testing", "devops",
        "software development",
    },
    "Networks & Cloud": {
        "network", "networks", "cloud", "distributed", "wireless", "networking",
    },
    "Databases": {
        "database", "sql", "data management", "dbms",
    },
    "Game & Multimedia": {
        "game", "multimedia", "graphics", "animation", "augmented reality",
        "virtual reality",
    },
}


def _stem(word):
    """Light suffix stemmer so 'network' matches 'networks' and
    'sensor' matches 'sensors' (no NLTK dependency)."""
    if len(word) <= 3:
        return word
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 5:
        return word[:-3]
    if word.endswith("ed") and len(word) > 4:
        return word[:-2]
    if word.endswith("es") and len(word) > 4 and not word.endswith("ss"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _stemmed_analyzer():
    """Default TF-IDF analyzer (lowercase + stopwords) + light stemming."""
    base = TfidfVectorizer(stop_words=STOPWORDS, lowercase=True).build_analyzer()
    return lambda doc: [_stem(t) for t in base(doc)]


def classify_domain(text):
    """Keyword-based domain classification; 'General' when nothing matches."""
    lowered = (text or "").lower()
    best_domain, best_hits = "General", 0
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best_domain, best_hits = domain, hits
    return best_domain


def _load_bert():
    """Load Sentence-BERT only when explicitly enabled (large download)."""
    if os.environ.get("USE_BERT") != "1":
        return None
    try:
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer("all-MiniLM-L6-v2")
    except Exception as exc:  # pragma: no cover - optional dependency
        print(f"BERT unavailable ({exc}); falling back to TF-IDF only.")
        return None


BERT_MODEL = _load_bert()


def _matched_keywords(analyzer, feature_index, weights, idea_text, interests):
    query_terms = set(analyzer(idea_text))
    interest_terms = set(analyzer(interests))
    common = query_terms & interest_terms
    if not common:
        return []
    return sorted(common, key=lambda term: -weights[feature_index[term]])


def match_idea(idea_text, supervisors, top_n=5, use_domain_boost=True,
               use_capacity_filter=True, use_verified_boost=True,
               use_bert=None):
    """Rank supervisors for an idea.

    supervisors: dicts from database.get_supervisors() (must include
    user_id, name, department, designation, email, research_interests,
    capacity, current_load, record_type).
    use_bert: None = use BERT when the model is loaded (live default),
    True = force the hybrid blend, False = TF-IDF only (so the evaluation
    can compare methods honestly even when BERT is loaded).
    Returns (results, method) where method names the scoring used.
    """
    available = []
    for sup in supervisors:
        capacity = sup.get("capacity") or 5
        load = sup.get("current_load") or 0
        if use_capacity_filter and load >= capacity:
            continue  # fully loaded supervisors are never recommended
        available.append(sup)
    if not available:
        return [], "tfidf"

    interests = [(s.get("research_interests") or "") for s in available]
    vectorizer = TfidfVectorizer(analyzer=_stemmed_analyzer())
    tfidf_matrix = vectorizer.fit_transform(interests)
    analyzer = vectorizer.build_analyzer()
    feature_index = {f: i for i, f in enumerate(vectorizer.get_feature_names_out())}
    query_vec = vectorizer.transform([idea_text])
    tfidf_scores = cosine_similarity(query_vec, tfidf_matrix)[0]

    bert_scores = None
    bert_on = BERT_MODEL is not None if use_bert is None else bool(use_bert)
    if bert_on and BERT_MODEL is not None:
        idea_emb = BERT_MODEL.encode([idea_text])
        sup_emb = BERT_MODEL.encode(interests)
        bert_scores = cosine_similarity(idea_emb, sup_emb)[0]

    domain = classify_domain(idea_text)
    domain_keywords = DOMAIN_KEYWORDS.get(domain, set())

    results = []
    for i, sup in enumerate(available):
        tfidf = float(tfidf_scores[i])
        if bert_scores is not None:
            score = 0.4 * tfidf + 0.6 * float(bert_scores[i])
            method = "hybrid (0.4 TF-IDF + 0.6 BERT)"
        else:
            score = tfidf
            method = "tfidf"
        interests_lower = (sup.get("research_interests") or "").lower()
        domain_matched = any(kw in interests_lower for kw in domain_keywords)
        if use_domain_boost and domain_matched and domain != "General":
            score = min(score + 0.10, 1.0)  # roadmap domain boost
        if (use_verified_boost and sup.get("record_type") == "Real"
                and domain_matched and domain != "General"):
            # Verified faculty profiles rank a little higher than the
            # clearly-labelled synthetic sample rows, but only when their
            # interests genuinely match the idea's domain.
            score = min(score + 0.10, 1.0)
        capacity = sup.get("capacity") or 5
        load = sup.get("current_load") or 0
        if capacity > 0:
            score = score * (1 - load / capacity * 0.2)  # load adjustment
        weights = tfidf_matrix[i].toarray()[0]
        keywords = _matched_keywords(
            analyzer, feature_index, weights, idea_text,
            sup.get("research_interests") or "",
        )
        explanation = f"Matched on: {', '.join(keywords)}" if keywords else "General profile match"
        if domain_matched and domain != "General":
            explanation += f". Domain: {domain}"
        results.append({
            "supervisor_id": sup["user_id"],
            "name": sup["name"],
            "department": sup.get("department"),
            "designation": sup.get("designation"),
            "email": sup["email"],
            "interests": sup.get("research_interests"),
            "record_type": sup.get("record_type"),
            "capacity": capacity,
            "current_load": load,
            "score": round(score, 4),
            "score_percent": round(score * 100, 1),
            "matched_keywords": keywords,
            "explanation": explanation,
        })
    results.sort(key=lambda r: -r["score"])
    return results[:top_n], (method if available else "tfidf")


# ---------------------------------------------------------------------------
# v5: gibberish detection, idea quality checker, uniqueness check
# ---------------------------------------------------------------------------

VOWELS = set("aeiouy")

TECH_ACRONYMS = {
    "ai", "ml", "nlp", "iot", "api", "sql", "css", "html", "cnn", "rnn",
    "lstm", "gan", "svm", "aws", "gpu", "cpu", "ui", "ux", "ar", "vr",
    "crud", "erp", "crm", "sms", "otp", "qr", "pdf", "url", "http",
    "https", "json", "xml", "ios", "php", "java", "c", "c++", "go",
    "rust", "r", "fyp", "sbbu", "dbms", "etl", "ci", "cd",
}

TECH_WORDS = {
    "python", "java", "javascript", "flutter", "react", "node", "nodejs",
    "android", "ios", "kotlin", "swift", "django", "flask", "fastapi",
    "mysql", "postgresql", "mongodb", "sqlite", "firebase", "tensorflow",
    "pytorch", "scikit-learn", "sklearn", "pandas", "numpy", "opencv",
    "blockchain", "ethereum", "solidity", "smart contract", "cloud",
    "aws", "azure", "docker", "kubernetes", "arduino", "raspberry pi",
    "unity", "c#", "c++", "php", "laravel", "vue", "angular", "html",
    "css", "api", "rest", "graphql", "websocket", "sensor", "robot",
    "drone", "chatbot", "dashboard", "mobile app", "web app", "website",
    "database", "machine learning", "deep learning", "neural network",
    "computer vision", "natural language processing", "nlp",
}

_KEYBOARD_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")


def _token_is_gibberish(token):
    """True when a single token looks like random letters.

    A token is suspicious when it has almost no vowels, a very long
    consonant run, or a run of keys from one keyboard row (qwerty/asdf).
    Known tech acronyms and short tokens are never flagged.
    """
    t = token.strip(".,;:!?()[]{}\"'").lower()
    if len(t) < 4 or t in TECH_ACRONYMS or not t.isalpha():
        return False
    vowels = sum(1 for ch in t if ch in VOWELS)
    if vowels == 0:
        return True
    if vowels / len(t) < 0.15:
        # also needs a long consonant run, so real words like
        # "strengths" are not flagged on ratio alone
        run = max_run = 0
        for ch in t:
            if ch in VOWELS:
                run = 0
            else:
                run += 1
                max_run = max(max_run, run)
        if max_run >= 4:
            return True
    run = max_run = 0
    for ch in t:
        if ch in VOWELS:
            run = 0
        else:
            run += 1
            max_run = max(max_run, run)
    if max_run >= 6:
        return True
    for row in _KEYBOARD_ROWS:
        for i in range(len(row) - 3):
            if row[i:i + 4] in t or row[i:i + 4][::-1] in t:
                return True
    return False


def detect_gibberish(text):
    """Detect random-letter input like 'sdfgdsjfgfsdhfsdfsdfsdifkj'.

    Returns {is_gibberish, score (share of suspicious tokens),
    suspicious_tokens, reasons}.
    """
    tokens = re.findall(r"[A-Za-z]+", text or "")
    if not tokens:
        return {"is_gibberish": False, "score": 0.0,
                "suspicious_tokens": [], "reasons": []}
    suspicious = [t for t in tokens if _token_is_gibberish(t)]
    ratio = len(suspicious) / len(tokens)
    is_gib = (len(tokens) == 1 and len(suspicious) == 1) or ratio >= 0.5
    reasons = []
    if is_gib:
        if ratio >= 0.5:
            reasons.append(
                f"{len(suspicious)} of {len(tokens)} words look like random letters")
        if suspicious:
            reasons.append(
                "no real words detected (for example: "
                + ", ".join(suspicious[:3]) + ")")
    return {
        "is_gibberish": is_gib,
        "score": round(ratio, 2),
        "suspicious_tokens": suspicious[:5],
        "reasons": reasons,
    }


def check_idea_quality(title, description):
    """Score an idea description 0-100 and suggest how to improve it.

    Score parts: length (30), domain keywords (30), named technology
    (25), title + description structure (15). Gibberish scores 0.
    Returns {score, grade, word_count, domain, keyword_hits, tech_terms,
    suggestions, gibberish}.
    """
    title = (title or "").strip()
    description = (description or "").strip()
    text = f"{title} {description}".strip()
    gib = detect_gibberish(text)
    tokens = re.findall(r"[A-Za-z]+", text)
    word_count = len(tokens)
    domain = classify_domain(text)
    lowered = text.lower()
    domain_kws = DOMAIN_KEYWORDS.get(domain, set())
    keyword_hits = sorted(kw for kw in domain_kws if kw in lowered)
    tech_terms = sorted(tw for tw in TECH_WORDS if tw in lowered)

    if gib["is_gibberish"]:
        return {
            "score": 0, "grade": "Gibberish", "word_count": word_count,
            "domain": domain, "keyword_hits": keyword_hits,
            "tech_terms": tech_terms,
            "suggestions": [
                "This looks like random characters, not a project idea.",
                "Please describe your project in words, for example: "
                "'AI chatbot that answers admission questions for new students.'",
            ],
            "gibberish": gib,
        }

    score = 0
    score += round(min(word_count, 20) / 20 * 30)
    score += 30 if len(keyword_hits) >= 3 else (22 if len(keyword_hits) == 2
                                                 else (12 if keyword_hits else 0))
    score += 25 if len(tech_terms) >= 3 else (18 if len(tech_terms) == 2
                                               else (10 if tech_terms else 0))
    title_words = len(re.findall(r"[A-Za-z]+", title))
    desc_words = len(re.findall(r"[A-Za-z]+", description))
    score += 15 if (title_words >= 3 and desc_words >= 8) else (
        7 if (title_words >= 3 or desc_words >= 8) else 0)
    score = min(score, 100)
    grade = ("Strong" if score >= 80 else "Good" if score >= 60
             else "Fair" if score >= 40 else "Weak")

    suggestions = []
    if word_count < 8:
        suggestions.append(
            "Add more detail - describe the problem and what your system will "
            "do (aim for 15+ words).")
    if not keyword_hits:
        suggestions.append(
            "Mention the domain clearly, for example: cybersecurity, machine "
            "learning, web development, IoT.")
    elif len(keyword_hits) < 3:
        suggestions.append(
            "Add 1-2 more domain keywords so the matcher can tell your idea "
            "apart from similar ones.")
    if not tech_terms:
        suggestions.append(
            "Name the technology you will use, for example: Python, Flutter, "
            "blockchain, MySQL.")
    if not any(w in lowered for w in
               ("problem", "issue", "difficult", "manual", "help", "solve",
                "struggle", "lack")):
        suggestions.append(
            "Say what problem it solves and who it helps.")
    if not suggestions:
        suggestions.append(
            "Well written - clear domain, technology and problem. Ready to match.")
    return {
        "score": score, "grade": grade, "word_count": word_count,
        "domain": domain, "keyword_hits": keyword_hits,
        "tech_terms": tech_terms, "suggestions": suggestions,
        "gibberish": gib,
    }


def _load_past_titles():
    """Sample archive of past FYP titles (demo data, not university records)."""
    path = os.path.join(os.path.dirname(__file__), "..", "past_fyp_titles.csv")
    titles = []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                titles.append((row["title"], row.get("domain", "")))
    except Exception:
        titles = [
            ("Online examination system for universities", "Web Development"),
            ("Smart home automation system using IoT", "IoT & Robotics"),
            ("Machine learning model for heart disease prediction",
             "Artificial Intelligence & ML"),
        ]
    return titles


PAST_TITLES = _load_past_titles()


def check_uniqueness(idea_text):
    """Compare an idea with the past-FYP archive by TF-IDF similarity.

    Returns {max_similarity, closest_title, closest_domain, verdict}.
    Verdicts: 'Very similar' (>= 0.55), 'Somewhat similar' (>= 0.35),
    otherwise 'Looks original'.
    """
    titles = [t for t, _ in PAST_TITLES]
    if not titles or not (idea_text or "").strip():
        return {"max_similarity": 0.0, "closest_title": None,
                "closest_domain": None, "verdict": "Looks original"}
    # Fit on past titles AND the idea, so the idea's own unique words
    # count against the similarity (a shared generic word like "smart"
    # alone must not make two different projects look identical).
    vectorizer = TfidfVectorizer(analyzer=_stemmed_analyzer())
    matrix = vectorizer.fit_transform(titles + [idea_text])
    title_matrix = matrix[:-1]
    query = matrix[-1]
    sims = cosine_similarity(query, title_matrix)[0]
    best = int(sims.argmax())
    sim = round(float(sims[best]), 3)
    verdict = ("Very similar" if sim >= 0.6 else
               "Somewhat similar" if sim >= 0.4 else "Looks original")
    return {
        "max_similarity": sim,
        "closest_title": titles[best],
        "closest_domain": PAST_TITLES[best][1],
        "verdict": verdict,
    }
