"""Genel OpenAI-uyumlu LLM istemcisi (chat/completions).

Binlerce saglayiciyi destekler: OpenAI, Gemini (OpenAI endpoint'i),
OpenRouter, Groq, Mistral, DeepSeek, Ollama (yerel, keysiz)...
Kullanici base_url + model + api_key verir; modele ozel kod gerekmez.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import config

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Sen bir is ilani filtreleme asistanisin. Kullanici profiline gore ilanlarin "
    "uygunlugunu 0-100 arasi puanlarsin. Ciktiyi SADECE gecerli JSON olarak ver, baska "
    "hicbir metin yazma. Format: {\"score\": 0-100 tamsayi, \"reason\": \"kisa gerekce\"}"
)

MAX_WORKERS = 4
BODY_CAP = 1500


def build_endpoint(base_url: str) -> str:
    path = base_url.strip().rstrip("/")
    if path.endswith("/chat/completions"):
        return path
    return f"{path}/chat/completions"


def _post_chat(base_url: str, api_key: str, model: str, messages: list[dict], timeout: int):
    endpoint = build_endpoint(base_url)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 200,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    attempts = [(payload.copy(), True), (payload.copy(), False)]
    last_err = None
    for body, use_format in attempts:
        if use_format:
            body["response_format"] = {"type": "json_object"}
        else:
            body.pop("response_format", None)
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_err = exc
            if exc.code != 400 and exc.code != 422:
                break
            # JSON destegi yoksa (Ollama/Gemini vb.) response_format olmadan dene
            continue
        except Exception as exc:  # network vb.
            last_err = exc
            break
    raise last_err


def extract_content(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("beklenmeyen yanit yapisi") from None


def parse_score(content: str) -> tuple[int, str]:
    text = content.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    obj = json.loads(text)
    score = int(obj.get("score", 0))
    score = max(0, min(100, score))
    return score, str(obj.get("reason", "") or "").strip()


def _build_messages(profile: str, post: dict) -> list[dict]:
    body = (post.get("body") or "")[:BODY_CAP]
    user = (
        "KULLANICI PROFILI (CV / kendini tanitma / istekler):\n"
        f"{profile}\n\n"
        "ILAN:\n"
        f"Baslik: {post.get('title', '')}\n"
        f"Subreddit: r/{post.get('subreddit', '')}\n"
        f"Bolge: {post.get('author', '')}\n"
        f"Ilan Metni:\n{body}\n\n"
        "Uygunluk puanini ver:"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def score_one(post: dict, profile: str, base_url: str, api_key: str, model: str,
              timeout: int) -> tuple[int, str]:
    messages = _build_messages(profile, post)
    data = _post_chat(base_url, api_key, model, messages, timeout)
    content = extract_content(data)
    return parse_score(content)


def score_posts(posts: list[dict], profile: str, base_url: str, api_key: str,
                model: str, timeout: int = config.LLM_TIMEOUT) -> dict[str, dict]:
    """Posts'lari paralel puanlar. {post_id: {'score':..., 'reason':...}} dondurur."""
    results: dict[str, dict] = {}
    args = [(p, profile, base_url, api_key, model, timeout) for p in posts]

    def work(item):
        post, *rest = item
        try:
            score, reason = score_one(post, *rest)
            return post["id"], {"score": score, "reason": reason}
        except Exception as exc:
            log.warning("ai puanlama hatasi %s: %s", post["id"], exc)
            return post["id"], {"score": None, "reason": f"error: {exc}"}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        for post_id, info in pool.map(work, args):
            results[post_id] = info
    return results