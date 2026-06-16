from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from typing import Any


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)

STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "both", "but", "by", "can", "cannot",
    "could", "did", "do", "does", "doing", "don", "down", "during", "each",
    "few", "for", "from", "further", "had", "has", "have", "having", "he",
    "her", "here", "hers", "herself", "him", "himself", "his", "how", "i",
    "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more",
    "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on",
    "once", "one", "only", "or", "other", "our", "ours", "ourselves", "out",
    "over", "own", "same", "she", "should", "so", "some", "such", "than",
    "that", "the", "their", "theirs", "them", "themselves", "then", "there",
    "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where",
    "which", "while", "who", "whom", "why", "will", "with", "would", "you",
    "your", "yours", "yourself", "yourselves", "president", "donald",
    "trump", "djt",
    "http", "https", "www", "com", "org", "net", "html", "truthsocial",
    "truth", "social", "status", "statuses", "users", "user", "link",
    "utm", "amp", "nbsp",
}

COUNTRIES = {
    "China": ["china", "chinese", "beijing", "xi", "ccp", "taiwan", "hong kong"],
    "United States": ["america", "american", "usa", "u.s.", "united states"],
    "Israel": ["israel", "israeli"],
    "Iran": ["iran", "iranian"],
    "Russia": ["russia", "russian", "putin"],
    "Ukraine": ["ukraine", "ukrainian", "zelensky"],
    "Mexico": ["mexico", "mexican"],
    "Canada": ["canada", "canadian"],
    "India": ["india", "indian"],
    "Japan": ["japan", "japanese"],
    "North Korea": ["north korea", "kim jong"],
    "United Kingdom": ["uk", "u.k.", "britain", "british", "england"],
}

CHINA_KEYWORDS = {
    "china", "chinese", "ccp", "beijing", "xi", "taiwan", "hong kong",
    "tariff", "tiktok", "trade war", "communist", "communists",
}

TOPIC_KEYWORDS = {
    "外交与战争": ["war", "peace", "ceasefire", "iran", "israel", "russia", "ukraine", "nato"],
    "经济与就业": ["jobs", "employment", "growth", "inflation", "gdp", "economy", "tariff"],
    "股市与金融": ["stock", "stocks", "market", "nasdaq", "dow", "s&p", "wall street", "fed"],
    "选举与背书": ["endorse", "endorsement", "election", "vote", "governor", "senate", "congress"],
    "移民与边境": ["border", "immigration", "ice", "illegal", "migrant"],
    "司法与调查": ["judge", "court", "law", "lawsuit", "indict", "investigation"],
    "媒体批评": ["fake news", "media", "fox", "cnn", "nytimes", "washington post"],
    "对华议题": list(CHINA_KEYWORDS),
    "国内治理": ["white house", "dc", "washington", "military", "police", "crime"],
}

POSITIVE_WORDS = {
    "great", "good", "excellent", "strong", "win", "winning", "record", "growth",
    "beautiful", "amazing", "success", "thank", "congratulations", "love",
}

NEGATIVE_WORDS = {
    "bad", "terrible", "horrible", "crooked", "corrupt", "fake", "weak", "stupid",
    "disaster", "crime", "war", "inflation", "rigged", "illegal", "fraud",
}

MARKET_KEYWORDS = {
    "stock", "stocks", "stock market", "market", "nasdaq", "dow", "s&p",
    "jobs report", "inflation", "growth", "fed", "tariff", "economy", "wall street",
}


def tokenize(text: str) -> list[str]:
    text = URL_RE.sub(" ", text or "")
    return [
        token.lower().strip("'")
        for token in TOKEN_RE.findall(text)
        if len(token) > 2 and token.lower() not in STOPWORDS
    ]


def analyze_all_posts(conn: sqlite3.Connection, only_missing: bool = True) -> dict[str, Any]:
    if only_missing:
        rows = conn.execute(
            """
            SELECT p.* FROM posts p
            LEFT JOIN post_china_relevance c ON c.post_id = p.id
            WHERE c.post_id IS NULL
            ORDER BY p.published_at_utc
            """
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM posts ORDER BY published_at_utc").fetchall()
    analyzed = 0
    for row in rows:
        analyze_post(conn, dict(row))
        analyzed += 1
    conn.commit()
    return {"analyzed": analyzed}


def analyze_post(conn: sqlite3.Connection, post: dict[str, Any]) -> None:
    post_id = int(post["id"])
    content_text = post.get("content_clean") or ""
    context_text = f"{post.get('title') or ''} {content_text}"
    words = tokenize(content_text)
    counter = Counter(words)

    _clear_analysis(conn, post_id)
    for term, count in counter.most_common(200):
        conn.execute(
            "INSERT OR REPLACE INTO post_terms(post_id, term, count) VALUES (?, ?, ?)",
            (post_id, term, count),
        )

    countries = detect_countries(context_text)
    for country, hits in countries.items():
        conn.execute(
            """
            INSERT INTO post_entities
              (post_id, entity_text, entity_type, normalized_name, confidence, source)
            VALUES (?, ?, 'country', ?, ?, 'rule')
            """,
            (post_id, ", ".join(hits), country, min(1.0, 0.5 + len(hits) * 0.15)),
        )

    for topic, confidence, reason in detect_topics(context_text):
        conn.execute(
            "INSERT INTO post_topics(post_id, topic, confidence, source, reason) VALUES (?, ?, ?, 'rule', ?)",
            (post_id, topic, confidence, reason),
        )

    china = detect_china_relevance(context_text)
    conn.execute(
        """
        INSERT OR REPLACE INTO post_china_relevance
          (post_id, is_related, score, matched_keywords, reason, source, analyzed_at)
        VALUES (?, ?, ?, ?, ?, 'rule', CURRENT_TIMESTAMP)
        """,
        (
            post_id,
            1 if china["is_related"] else 0,
            china["score"],
            json.dumps(china["matched_keywords"], ensure_ascii=False),
            china["reason"],
        ),
    )

    sentiment = detect_sentiment(words)
    conn.execute(
        """
        INSERT INTO post_sentiments(post_id, polarity, score, intensity, tones, source)
        VALUES (?, ?, ?, ?, ?, 'rule')
        """,
        (
            post_id,
            sentiment["polarity"],
            sentiment["score"],
            sentiment["intensity"],
            json.dumps(sentiment["tones"], ensure_ascii=False),
        ),
    )

    signal = detect_market_signal(context_text, sentiment)
    if signal:
        conn.execute(
            """
            INSERT INTO post_market_signals
              (post_id, signal_type, signal_score, related_symbols, event_window, reason, source)
            VALUES (?, ?, ?, ?, 'T+1,T+3,T+5', ?, 'rule')
            """,
            (
                post_id,
                signal["signal_type"],
                signal["signal_score"],
                json.dumps(["SPY", "QQQ", "DIA"]),
                signal["reason"],
            ),
        )


def detect_countries(text: str) -> dict[str, list[str]]:
    low = text.lower()
    found: dict[str, list[str]] = {}
    for country, keys in COUNTRIES.items():
        hits = [key for key in keys if key in low]
        if hits:
            found[country] = hits
    return found


def detect_topics(text: str) -> list[tuple[str, float, str]]:
    low = text.lower()
    topics: list[tuple[str, float, str]] = []
    for topic, keys in TOPIC_KEYWORDS.items():
        hits = [key for key in keys if key in low]
        if hits:
            score = min(1.0, 0.45 + math.log1p(len(hits)) / 2)
            topics.append((topic, score, "命中关键词: " + ", ".join(hits[:8])))
    if not topics:
        topics.append(("其他", 0.35, "未命中主要主题词典"))
    return topics


def detect_china_relevance(text: str) -> dict[str, Any]:
    low = text.lower()
    matched = sorted([key for key in CHINA_KEYWORDS if key in low])
    score = min(1.0, len(matched) * 0.22)
    return {
        "is_related": score >= 0.22,
        "score": score,
        "matched_keywords": matched,
        "reason": "命中中国相关关键词" if matched else "未命中中国相关关键词",
    }


def detect_sentiment(words: list[str]) -> dict[str, Any]:
    pos = sum(1 for word in words if word in POSITIVE_WORDS)
    neg = sum(1 for word in words if word in NEGATIVE_WORDS)
    total = max(1, pos + neg)
    score = (pos - neg) / total
    if score > 0.15:
        polarity = "positive"
    elif score < -0.15:
        polarity = "negative"
    else:
        polarity = "neutral"
    tones = []
    if pos >= 2:
        tones.append("赞扬/庆祝")
    if neg >= 2:
        tones.append("攻击/警告")
    if not tones:
        tones.append("陈述")
    return {
        "polarity": polarity,
        "score": round(score, 4),
        "intensity": round(min(1.0, (pos + neg) / 8), 4),
        "tones": tones,
    }


def detect_market_signal(text: str, sentiment: dict[str, Any]) -> dict[str, Any] | None:
    low = text.lower()
    hits = [key for key in MARKET_KEYWORDS if key in low]
    if not hits:
        return None
    score = min(1.0, 0.35 + len(hits) * 0.12 + abs(float(sentiment["score"])) * 0.2)
    if sentiment["polarity"] == "negative":
        signal_type = "bearish"
    elif sentiment["polarity"] == "positive":
        signal_type = "bullish"
    else:
        signal_type = "neutral"
    return {
        "signal_type": signal_type,
        "signal_score": round(score, 4),
        "reason": "命中美股/经济关键词: " + ", ".join(hits[:8]),
    }


def _clear_analysis(conn: sqlite3.Connection, post_id: int) -> None:
    for table in [
        "post_terms",
        "post_entities",
        "post_topics",
        "post_china_relevance",
        "post_sentiments",
        "post_market_signals",
    ]:
        conn.execute(f"DELETE FROM {table} WHERE post_id = ?", (post_id,))
