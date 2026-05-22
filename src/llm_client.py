from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from openai import OpenAI

    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


def is_llm_configured() -> bool:
    key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    return bool(key and HAS_OPENAI)


def _client() -> "OpenAI":
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or None
    return OpenAI(api_key=api_key, base_url=base_url)


def default_model() -> str:
    return os.getenv("LLM_MODEL", "gpt-4o-mini")


def use_vision() -> bool:
    return os.getenv("USE_LLM_VISION", "true").lower() in {"1", "true", "yes", "y"}


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return json.loads(match.group())
        raise


def _image_message_part(path: Path) -> Optional[Dict[str, Any]]:
    ext = path.suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return None
    mime = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/jpeg")
    data = base64.b64encode(path.read_bytes()).decode("utf-8")
    return {
        "type": "image_url",
        "image_url": {"url": f"data:{mime};base64,{data}"},
    }


def chat_json(
    system_prompt: str,
    user_prompt: str,
    image_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not is_llm_configured():
        raise RuntimeError("LLM is not configured. Set OPENAI_API_KEY or LLM_API_KEY.")

    client = _client()
    model = default_model()

    user_content: Any
    if image_path and use_vision() and _image_message_part(image_path):
        user_content = [
            {"type": "text", "text": user_prompt},
            _image_message_part(image_path),
        ]
    else:
        user_content = user_prompt

    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    content = response.choices[0].message.content or "{}"
    return _extract_json(content)
