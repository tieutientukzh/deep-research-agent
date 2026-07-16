"""Test cho tool ``fetch_url``.

Ta dùng fixture ``httpx_mock`` của pytest-httpx để chặn HTTP ở tầng transport, nên code
httpx thật vẫn chạy (redirect, headers, xử lý status) mà không đụng mạng. Sau đó trafilatura
trích nội dung từ HTML giả một cách thật sự.
"""

from __future__ import annotations

import httpx

from deep_research_agent.tools.fetch import fetch_url

# Một bài viết nhỏ nhưng trông thật: đủ văn xuôi để trafilatura nhận ra nội dung chính.
_ARTICLE_HTML = """
<html><head><title>Quantization guide</title></head>
<body>
<nav>home about contact</nav>
<article>
<h1>LLM Quantization</h1>
<p>Quantization reduces the numerical precision of model weights from sixteen bits down
to eight or even four bits. This shrinks memory usage and speeds up inference on
commodity hardware without retraining the model from scratch.</p>
<p>Post-training quantization is the simplest approach: you take an already trained
network and convert its weights afterwards. More advanced schemes calibrate on a small
dataset to keep the accuracy loss small.</p>
</article>
</body></html>
"""


async def test_fetch_extracts_main_text(httpx_mock) -> None:
    httpx_mock.add_response(url="https://example.com/article", html=_ARTICLE_HTML)

    res = await fetch_url("https://example.com/article")

    assert res.ok
    assert res.status_code == 200
    assert "Quantization reduces" in res.text
    # Phần điều hướng (nav) rác phải bị bộ trích nội dung chính loại bỏ.
    assert "home about contact" not in res.text


async def test_fetch_non_200_records_error(httpx_mock) -> None:
    httpx_mock.add_response(url="https://example.com/missing", status_code=404)

    res = await fetch_url("https://example.com/missing")

    assert not res.ok
    assert res.status_code == 404
    assert "404" in (res.error or "")
    assert res.text is None


async def test_fetch_network_error_records_error(httpx_mock) -> None:
    httpx_mock.add_exception(
        httpx.ReadTimeout("timed out"), url="https://example.com/slow"
    )

    res = await fetch_url("https://example.com/slow")

    assert not res.ok
    assert "request failed" in (res.error or "")


async def test_fetch_empty_page_records_no_content(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://example.com/empty", html="<html><body></body></html>"
    )

    res = await fetch_url("https://example.com/empty")

    assert not res.ok
    assert res.status_code == 200
    assert "no main content" in (res.error or "")
