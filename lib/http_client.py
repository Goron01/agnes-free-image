#!/usr/bin/env python3
"""
Agnes Free Image HTTP 客户端（v20260604 用 curl 子进程替代 urllib）

背景：
- OpenClaw 沙箱内 Python urllib 调用 HTTPS POST 会卡死 30 秒
- 同请求 system curl 1 秒成功
- 解决：用 curl 子进程替代 urllib，保持相同接口（return code + body）

提供：
- curl_request(method, url, headers, data, timeout) -> (http_code, body)
- CurlHTTPError: 模拟 urllib.error.HTTPError（保留 code / body 属性）
"""

import subprocess
import sys
from typing import Dict, Optional, Tuple, Union


def curl_request(
    url: str,
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Union[str, bytes]] = None,
    timeout: int = 180,
) -> Tuple[int, str]:
    """用 curl 子进程发 HTTP 请求，绕开 Python urllib 在 OpenClaw 沙箱卡死

    Args:
        url: 请求 URL
        method: HTTP method (默认 POST)
        headers: dict of header name -> value
        data: request body (str or bytes)
        timeout: 超时秒数（同时传给 curl --max-time 和 subprocess 兜底）

    Returns:
        (http_code, body_str) - http_code=0 表示超时/连接错误
    """
    cmd = [
        "curl", "-s",
        "-w", "\n__HTTP_CODE__:%{http_code}",
        "-X", method,
        "--max-time", str(timeout),
    ]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    if data is not None:
        if isinstance(data, bytes):
            data = data.decode("utf-8", errors="ignore")
        cmd += ["--data", data]
    cmd.append(url)

    # subprocess 兜底超时 = curl --max-time + 5s
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired:
        print(f"# [curl_request] subprocess timeout after {timeout + 5}s",
              file=sys.stderr)
        return 0, ""
    except Exception as e:
        print(f"# [curl_request] error: {type(e).__name__}: {e}", file=sys.stderr)
        return 0, ""

    body = r.stdout or ""
    # 末尾提取 http code
    http_code = 0
    if "__HTTP_CODE__:" in body:
        idx = body.rfind("__HTTP_CODE__:")
        try:
            http_code_str = body[idx + len("__HTTP_CODE__:"):].strip()
            http_code = int(http_code_str)
            body = body[:idx].rstrip()
        except (ValueError, IndexError):
            pass

    # 如果 curl 写到了 stderr 一些警告但实际有响应
    if not body and r.stderr:
        body = r.stderr

    return http_code, body
