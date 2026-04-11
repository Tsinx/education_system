import json
import re
from typing import Any

import httpx
from loguru import logger

from app.core.config import settings

_URL_PATTERN = re.compile(r"https?://[^\s<>\]\)\"']+")


def _normalize_auth_header(api_key: str) -> str:
    token = api_key.strip()
    if not token:
        return ""
    if token.lower().startswith("bearer "):
        return token
    return f"Bearer {token}"


def _parse_mcp_sse_payload(raw: str) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    for line in raw.splitlines():
        text = line.strip()
        if not text.startswith("data:"):
            continue
        payload = text[5:].strip()
        if not payload:
            continue
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            messages.append(parsed)
    return messages[-1] if messages else {}


def _decode_nested_json_text(value: str) -> Any:
    current: Any = value
    for _ in range(3):
        if not isinstance(current, str):
            return current
        text = current.strip()
        try:
            current = json.loads(text)
        except json.JSONDecodeError:
            return text
    return current


def _extract_text_blocks(result: dict[str, Any]) -> list[str]:
    content = result.get("content")
    if not isinstance(content, list):
        return []
    texts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text.strip())
    return texts


def _truncate(text: str, max_chars: int) -> str:
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    return clean[:max_chars] + "\n\n（以下内容因长度限制已截断）"


def _extract_urls(texts: list[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for text in texts:
        for match in _URL_PATTERN.findall(text):
            url = match.rstrip(".,);]")
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
    return urls


async def _call_mcp_tool(server_url: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    api_key = settings.bigmodel_mcp_api_key.strip()
    if not api_key:
        return {"ok": False, "error": "未配置 BigModel MCP API Key"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "Authorization": _normalize_auth_header(api_key),
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.bigmodel_mcp_timeout_s)) as client:
            response = await client.post(server_url, headers=headers, json=payload)
            response.raise_for_status()
    except Exception as exc:
        logger.warning("MCP 工具调用失败 | tool={} | err={}", tool_name, exc)
        return {"ok": False, "error": str(exc)}

    message = _parse_mcp_sse_payload(response.text)
    result = message.get("result", {}) if isinstance(message, dict) else {}
    texts = _extract_text_blocks(result if isinstance(result, dict) else {})
    joined = "\n\n".join(texts).strip()
    if isinstance(result, dict) and result.get("isError"):
        return {"ok": False, "error": joined or "MCP 工具返回错误", "raw": result}

    decoded_blocks: list[Any] = []
    for text in texts:
        decoded_blocks.append(_decode_nested_json_text(text))

    return {
        "ok": True,
        "text": joined,
        "decoded_blocks": decoded_blocks,
        "raw": result,
        "urls": _extract_urls(texts),
    }


async def search_web(search_query: str) -> dict[str, Any]:
    arguments = {
        "search_query": search_query[:70],
        "content_size": "medium",
        "search_recency_filter": "noLimit",
        "location": "cn",
    }
    return await _call_mcp_tool(settings.bigmodel_mcp_search_url, "web_search_prime", arguments)


async def read_web_page(url: str) -> dict[str, Any]:
    arguments = {
        "url": url,
        "timeout": min(max(settings.bigmodel_mcp_timeout_s, 10), 120),
        "return_format": "markdown",
        "retain_images": False,
        "with_images_summary": False,
        "with_links_summary": False,
        "no_cache": False,
    }
    result = await _call_mcp_tool(settings.bigmodel_mcp_reader_url, "webReader", arguments)
    if not result.get("ok"):
        return result

    decoded_blocks = result.get("decoded_blocks", [])
    page_text = result.get("text", "")
    for block in decoded_blocks:
        if isinstance(block, dict):
            if isinstance(block.get("content"), str) and block.get("content", "").strip():
                page_text = block["content"].strip()
                break
            if isinstance(block.get("markdown"), str) and block.get("markdown", "").strip():
                page_text = block["markdown"].strip()
                break
    return {
        "ok": True,
        "text": page_text,
        "raw": result.get("raw", {}),
    }


async def build_web_search_context(queries: list[str], max_queries: int = 3, max_reader_pages: int = 2) -> dict[str, Any]:
    normalized_queries = [q.strip() for q in queries if q.strip()][:max_queries]
    if not normalized_queries:
        return {"used_search": False, "markdown": "", "source_urls": [], "errors": []}

    lines = ["## 联网补充资料"]
    source_urls: list[str] = []
    errors: list[str] = []
    seen_urls: set[str] = set()
    reader_budget = max(0, max_reader_pages)
    used_search = False

    for query in normalized_queries:
        search_result = await search_web(query)
        if not search_result.get("ok"):
            errors.append(f"搜索失败：{query} | {search_result.get('error', '未知错误')}")
            continue
        used_search = True
        search_text = str(search_result.get("text", "")).strip()
        if search_text:
            lines.append(f"### 搜索主题：{query}")
            lines.append(_truncate(search_text, 2200))

        for url in search_result.get("urls", []):
            if reader_budget <= 0:
                break
            if url in seen_urls:
                continue
            seen_urls.add(url)
            source_urls.append(url)
            reader_result = await read_web_page(url)
            if not reader_result.get("ok"):
                errors.append(f"网页读取失败：{url} | {reader_result.get('error', '未知错误')}")
                continue
            page_text = str(reader_result.get("text", "")).strip()
            if not page_text:
                continue
            lines.append(f"#### 网页精读：{url}")
            lines.append(_truncate(page_text, 3000))
            reader_budget -= 1

    if source_urls:
        lines.append("## 参考链接")
        for idx, url in enumerate(source_urls, start=1):
            lines.append(f"{idx}. {url}")

    markdown = "\n\n".join(lines) if used_search else ""
    return {
        "used_search": used_search,
        "markdown": markdown,
        "source_urls": source_urls,
        "errors": errors,
    }
