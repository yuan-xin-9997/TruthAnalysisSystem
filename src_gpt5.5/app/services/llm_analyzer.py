from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class OpenAIAnalyzer:
    def __init__(self, model: str = "gpt-5.5", api_key: str | None = None) -> None:
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def analyze_post(self, title: str, content: str) -> dict[str, Any]:
        prompt = (
            "你是一个政治文本和金融影响研究助手。请基于给定 Truth Social 贴文，"
            "输出严格 JSON，字段包括 summary_zh, topics, entities, china_related, "
            "market_relevance, sentiment, reasoning。不要输出 JSON 以外的内容。\n\n"
            f"标题: {title}\n正文: {content}"
        )
        text = self._responses_create(prompt)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"raw_text": text}

    def summarize_range(self, posts: list[dict[str, Any]]) -> dict[str, Any]:
        snippets = "\n\n".join(
            f"- {p.get('published_date')}: {p.get('title')}\n{p.get('content_clean', '')[:800]}"
            for p in posts[:60]
        )
        prompt = (
            "请用中文总结以下特朗普 Truth Social 贴文集合。输出严格 JSON，字段包括 "
            "overview, main_topics, key_entities, china_related_findings, market_findings, "
            "notable_posts, risks。\n\n"
            f"{snippets}"
        )
        text = self._responses_create(prompt)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"overview": text}

    def _responses_create(self, input_text: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        payload = {"model": self.model, "input": input_text}
        request = urllib.request.Request(
            OPENAI_RESPONSES_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenAI API error {exc.code}: {body[:500]}") from exc
        if "output_text" in data:
            return data["output_text"]
        chunks: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                if content.get("type") in {"output_text", "text"} and content.get("text"):
                    chunks.append(content["text"])
        return "\n".join(chunks).strip()

