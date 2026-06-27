#!/usr/bin/env python3
"""Generate Agnes Image 2.1 Flash images and download URL results.

v2.1.0 优化（2026-06-05）：Agent 视角
- 加 --format {agent|json|human} 参数
- agent 模式：stdout 输出 STATUS/PATH/URL/PROMPT/SIZE 结构化字段，错误也走 stdout
- 默认 agent（AI agent 主要消费者）
- json 模式：保持 v2.0.1 行为（dump 完整 API 响应，错误走 stderr），用于调试

v2.0.1 修复（2026-06-04）：
- P0 bug: 5xx/429/网络错误路径补 `continue`，多 Key 轮换真正生效
- download: curl 加 `-f` flag + returncode 校验，防错误页被当图片

v2.0.0 优化（2026-06-04）：
- P1: urllib 沙箱卡死 → 改用 lib/http_client.py 的 curl_request
- P2: 加指数退避重试（5xx/超时/网络错误重试 3 次，429 等更久）
- P3: 多 Key 轮换（AGNES_API_KEY 逗号分隔，1 key 也兼容）
- P4: 错误处理更细：区分 4xx 不重试、5xx/超时/网络/429 才重试
- 删冗余 --response-format 参数（API 只支持 url）
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
import subprocess
import time
from typing import Any, Optional
from urllib import parse  # urlparse 给 filename_from_url 用

# v2.0.0: urllib.request 改用 curl_request（沙箱兼容）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
from http_client import curl_request  # noqa: E402


API_BASE = os.environ.get("AGNES_API_BASE", "https://apihub.agnes-ai.com").rstrip("/")
MODEL = "agnes-image-2.1-flash"

# v2.0.0 重试参数
MAX_RETRIES = 3
BASE_BACKOFF_SEC = 1.5  # 1.5s, 3s, 6s 退避
QUOTA_BACKOFF_SEC = 10  # 429/配额错误额外等待（秒）

# 视为可重试的 HTTP 状态码（4xx 业务错误不重试，但 429 例外）
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class ApiError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


# ---------------------------------------------------------------------------
# v2.0.0: Key 池管理
# ---------------------------------------------------------------------------

def get_api_keys() -> list[str]:
    """从环境变量读取 Key 池：AGNES_API_KEY=key1,key2,key3 或 AGNES_TOKEN 兜底

    返回去重且保持顺序的 Key 列表。
    """
    raw = os.environ.get("AGNES_API_KEY") or os.environ.get("AGNES_TOKEN") or ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    seen: set = set()
    deduped: list = []
    for k in keys:
        if k and k not in seen:
            seen.add(k)
            deduped.append(k)
    if not deduped:
        raise SystemExit("Missing API key. Set AGNES_API_KEY, for example: export AGNES_API_KEY='sk-xxx' or 'sk-a,sk-b'")
    return deduped


# ---------------------------------------------------------------------------
# v2.0.0: 错误分类
# ---------------------------------------------------------------------------

def is_quota_error(body: str, status: Optional[int]) -> bool:
    """判断响应正文是否表示配额/限流耗尽

    一些 API 在配额耗尽时用 401/403/429 + 关键词描述错误。
    本函数只看 body 文本，不限制状态码——调用方按需结合 status 一起判断。

    v2.2.0 修复：移除过于宽泛的"今天"等关键词（易误报），只保留
    与配额/限流强相关的精确短语，避免正常响应被误判为配额错误。
    """
    if not body:
        return False
    body_lower = body.lower()
    # 收紧关键词：要么是 quota/limit 专属英文术语，要么是中文"次数已用完"类短语
    # 避免"今天""建议您"等过宽词（会误判"今天是个好日子"等正常文本）
    quota_keywords = [
        # 英文（强相关）
        "quota", "rate limit", "limit reached", "rate exceeded",
        "insufficient quota", "insufficient_credit", "insufficient balance",
        "quota exceeded", "credit exhausted", "balance exhausted",
        # 中文（强相关，避免"今天"等宽泛词）
        "次数已用完", "配额已用完", "额度已用完", "余额不足",
        "已达调用上限", "已达上限", "超过限制", "超过上限",
        "调用上限", "超出限制", "超出上限", "达到上限",
        "limit reached", "rate-limit", "rate_limit",
    ]
    return any(kw in body_lower for kw in quota_keywords)


def is_retryable_status(status: int) -> bool:
    """判断是否值得重试：5xx / 429 / 网络错误（status=0）"""
    if status == 0:
        return True
    return status in RETRYABLE_STATUS


# ---------------------------------------------------------------------------
# v2.0.0: 带重试 + Key 轮换的请求
# ---------------------------------------------------------------------------

def request_json_with_retry(
    method: str,
    url: str,
    keys: list,
    payload: Optional[dict] = None,
    max_retries: int = MAX_RETRIES,
) -> dict:
    """带指数退避重试 + Key 轮换的 POST 请求

    策略：
    - 每轮重试：依次尝试所有 key（遇到可重试错误就切下一个）
    - 一轮 key 都用完后做指数退避（1.5s, 3s, 6s）
    - 429/配额错误额外等更久
    - 4xx 业务错误（除 429）立刻抛 ApiError，不重试
    """
    data_str: Optional[str] = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data_str = json.dumps(payload, ensure_ascii=False)

    last_error: Optional[ApiError] = None

    for attempt in range(max_retries):
        for key_index, key in enumerate(keys):
            headers["Authorization"] = f"Bearer {key}"
            try:
                code, body = curl_request(
                    url=url,
                    method=method,
                    headers=headers,
                    data=data_str,
                    timeout=180,
                )
            except Exception as e:
                last_error = ApiError(f"Network error: {e}")
                continue  # 切下一个 key

            # 成功
            if 200 <= code < 300:
                try:
                    parsed = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    raise ApiError(f"Expected JSON object, got: {body[:300]}")
                if isinstance(parsed, dict) and parsed.get("error"):
                    raise ApiError(_extract_err_msg(parsed) or "API returned an error", payload=parsed)
                if not isinstance(parsed, dict):
                    raise ApiError(f"Expected JSON object, got: {body[:300]}")
                return parsed

            # 业务错误（4xx，非 429）
            if 400 <= code < 500 and code not in RETRYABLE_STATUS:
                # 401/403 + quota 关键词：所有 key 都用完了（quota 跨 key 共享）→ 立刻报错
                if code in (401, 403) and is_quota_error(body, code):
                    raise ApiError(
                        f"Agnes API quota exhausted (HTTP {code}): {body[:200]}",
                        status=code,
                    )
                # 401/403 非 quota：单 key 鉴权失败 → 切成可重试错误，让外层切下一个 key
                if code in (401, 403):
                    last_error = ApiError(
                        f"Auth failed (HTTP {code}): {body[:200]}",
                        status=code,
                    )
                    print(
                        f"# [retry] attempt {attempt + 1}/{max_retries} key {key_index + 1}/{len(keys)} "
                        f"got auth error (status={code}), trying next key...",
                        file=sys.stderr,
                    )
                    continue  # 切下一个 key
                # 其他 4xx 业务错误：直接报错，不重试
                parsed = _try_parse_json(body)
                msg = _extract_err_msg(parsed) if isinstance(parsed, dict) else None
                raise ApiError(
                    msg or f"HTTP {code}: {body[:200]}",
                    status=code,
                    payload=parsed,
                )

            # 可重试错误（5xx / 429 / 网络）
            last_error = ApiError(
                f"HTTP {code}: {body[:200]}" if body else f"Network error (http_code={code})",
                status=code,
            )

            retry_kind = "quota" if (code == 429 or is_quota_error(body, code)) else "transient"
            print(
                f"# [retry] attempt {attempt + 1}/{max_retries} key {key_index + 1}/{len(keys)} "
                f"got {retry_kind} error (status={code}), trying next...",
                file=sys.stderr,
            )
            # 切下一个 key（5xx/429/网络错误也走轮换，符合 SKILL.md P3 文档承诺）
            continue

        # 一轮 key 都试过：指数退避
        if attempt < max_retries - 1:
            if last_error and (last_error.status == 429 or is_quota_error(str(last_error), last_error.status)):
                wait = QUOTA_BACKOFF_SEC * (attempt + 1)
            else:
                wait = BASE_BACKOFF_SEC * (2 ** attempt)  # 1.5, 3, 6
            print(f"# [retry] all keys exhausted, sleeping {wait:.1f}s before next round", file=sys.stderr)
            time.sleep(wait)

    raise last_error or ApiError("All retries exhausted with no error captured")


def _try_parse_json(body: str) -> Any:
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return body


def _extract_err_msg(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            return str(err.get("message") or err.get("type") or err)
        if isinstance(err, str):
            return err
        if payload.get("message"):
            return str(payload["message"])
    return None


# ---------------------------------------------------------------------------
# v1.0 保留函数
# ---------------------------------------------------------------------------


def validate_size(value: str) -> str:
    """校验并规范化 size 字符串，返回规范化后的合法值

    v2.2.1 修复：把规范化（大写 X → 小写 x、中文 × → 小写 x）提到返回值，
    调用方拿到的是保证可被 API 接受的纯 ASCII 小写 x 格式。
    不然会出现 validate_size 通过校验、但 build_payload 仍把 '1024X768'
    或 '1024×768' 发到 API 被 422 / 'invalid_request' 拒绝的情况（实测）。

    Returns:
        规范化后的合法 size 字符串（始终是 <int>x<int> 形式）

    Raises:
        SystemExit: 输入为空或格式非法
    """
    if not value:
        raise SystemExit("Missing --size. Use a pixel size such as 1024x768.")
    normalized = value.lower().replace("×", "x")
    if re.fullmatch(r"[1-9][0-9]{1,4}x[1-9][0-9]{1,4}", normalized) is None:
        raise SystemExit(
            f"Invalid size '{value}'. Use a pixel size such as 1024x768 "
            f"(common sizes: 1024x1024, 1024x768, 768x1024, 512x512)."
        )
    return normalized


def build_payload(args: argparse.Namespace) -> dict:
    # v2.2.1: validate_size 现在返回规范化值，build_payload 用规范化值（确保 API 接受）
    size = validate_size(args.size)
    payload: dict = {
        "model": MODEL,
        "prompt": args.prompt,
        "size": size,
    }
    # v2.0.0: image-to-image 时 images 必为 array（api.md 写死 array）
    if args.image_url:
        images = args.image_url if isinstance(args.image_url, list) else [args.image_url]
        payload["extra_body"] = {
            "image": images,
            "response_format": "url",
        }
    return payload


# v2.2.0: 复用上次产出的公网 URL（绕开 catbox 上传）
def is_agnes_cdn_url(url: str) -> bool:
    """判断 URL 是否为 Agnes API 自带的公网直链（可复用，无需再传图床）

    v2.2.0 覆盖三个官方 CDN 域名（实测）：
    - https://storage.googleapis.com/agnes-aigc/        (早期)
    - https://files.agnes-ai.com/                       (早期)
    - https://platform-outputs.agnes-ai.space/images/   (2026-06 主流)
    """
    if not url:
        return False
    return (
        url.startswith("https://storage.googleapis.com/agnes-aigc/")
        or url.startswith("https://files.agnes-ai.com/")
        or url.startswith("https://platform-outputs.agnes-ai.space/")
    )


def collect_urls(value: Any) -> list:
    urls: list = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"url", "image_url"} and isinstance(nested, str) and nested.startswith(("http://", "https://")):
                urls.append(nested)
            else:
                urls.extend(collect_urls(nested))
    elif isinstance(value, list):
        for item in value:
            urls.extend(collect_urls(item))
    return urls


def filename_from_url(url: str, index: int) -> str:
    parsed = parse.urlparse(url)
    name = Path(parsed.path).name
    if not name or "." not in name:
        ext = mimetypes.guess_extension("image/png") or ".png"
        name = f"agnes-image-{index:02d}{ext}"
    return name


def download_urls(urls: list, output_dir: str) -> list:
    """v2.0.0: 下载也走 curl（避免 urllib 沙箱卡死）"""
    directory = Path(output_dir).expanduser()
    directory.mkdir(parents=True, exist_ok=True)
    paths: list = []
    for index, url in enumerate(urls, start=1):
        path = directory / filename_from_url(url, index)
        # curl -L 跟随重定向，-o 写文件，-f 让 HTTP 错误返回非零退出码
        cmd = ["curl", "-s", "-L", "-f",
               "--max-time", "180",
               "-o", str(path), url]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=200)
        except Exception as exc:
            print(f"Download failed for {url}: {exc}", file=sys.stderr)
            continue
        if r.returncode != 0:
            # curl -f 模式下 HTTP 4xx/5xx 会让 returncode != 0，文件可能是错误页
            print(
                f"Download failed for {url}: curl exit {r.returncode}"
                + (f" ({r.stderr.strip()[:120]})" if r.stderr else ""),
                file=sys.stderr,
            )
            if path.exists():
                path.unlink(missing_ok=True)
            continue
        if not path.exists() or path.stat().st_size == 0:
            print(f"Download failed for {url}: empty file", file=sys.stderr)
            continue
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# v2.1.0: Agent-friendly 输出格式
# ---------------------------------------------------------------------------

def _print_agent_success(paths: list, urls: list, prompt: str, size: str) -> None:
    """agent 模式成功输出：结构化 key-value，每行一个字段，便于 AI agent 解析

    设计原则：
    - 所有信息都走 stdout（不混 stderr）
    - 关键字段是 PATH 和 URL（agent 拿来发图给主人）
    - 多张图时第一个用 PATH/URL，后续用 PATH_2/PATH_3 等
    - v2.2.0 修复：路径/URL 用 zip 配对，**不为没有 PATH 的 URL 输出孤立的 URL_2**
      （避免 agent 拿到 URL 但无对应本地路径的歧义场景）
    - v2.2.0 修复：若 paths 为空但 urls 非空（下载全部失败），由调用方决定
      是否走 STATUS: error 分支；这里只输出 ok + 警告注释
    """
    print("STATUS: ok")
    print(f"PROMPT: {prompt}")
    print(f"SIZE: {size}")
    if not paths and not urls:
        return
    # 用 paths 长度对齐，URLs 可能比 paths 多（部分下载失败）
    n = len(paths)
    for i in range(n):
        path_key = "PATH" if i == 0 else f"PATH_{i + 1}"
        url_key = "URL" if i == 0 else f"URL_{i + 1}"
        if i < len(paths):
            print(f"{path_key}: {paths[i]}")
        if i < len(urls):
            print(f"{url_key}: {urls[i]}")
    # 全部下载失败的提示：paths 空但 urls 非空，调用方会单独返回 error
    # 这里只在部分失败时输出未下载的 URL 到 stderr（避免 stdout 解析混淆）


def _print_agent_error(message: str, status: Optional[int] = None) -> None:
    """agent 模式错误输出：注意走 stdout 不是 stderr，agent 一定看得到"""
    print("STATUS: error")
    if status is not None:
        print(f"HTTP_STATUS: {status}")
    # 只取第一行、截断到 300 字符，避免吐一大堆
    first_line = str(message).split("\n")[0][:300]
    print(f"REASON: {first_line}")


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        return _cmd_generate_impl(args)
    except SystemExit as e:
        # v2.1.0: validate_size / get_api_keys 抛的 SystemExit，在 agent 模式走 stdout
        code = e.code if isinstance(e.code, int) else 1
        if code == 0:
            raise  # 正常退出不拦截
        if args.format == "agent":
            msg = str(e) if str(e) else "Invalid arguments"
            _print_agent_error(msg, status=None)
            return code
        raise  # 其他模式保持原行为（错误到 stderr）


def _cmd_generate_impl(args: argparse.Namespace) -> int:
    payload = build_payload(args)
    url = f"{args.api_base.rstrip('/')}/v1/images/generations"

    if args.dry_run:
        print(json.dumps({"url": url, "payload": payload}, ensure_ascii=False, indent=2))
        return 0

    keys = get_api_keys()
    try:
        response = request_json_with_retry("POST", url, keys, payload, max_retries=args.max_retries)
    except ApiError as exc:
        if args.format == "agent":
            # 错误走 stdout（agent 一定看得到）
            _print_agent_error(str(exc), exc.status)
        else:
            print(f"Agnes API error: {exc}", file=sys.stderr)
            if exc.payload is not None:
                print(json.dumps(exc.payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    urls = collect_urls(response)

    if args.format == "agent":
        # agent 模式：结构化输出，PATH 走 stdout
        paths: list = []
        if args.output_dir and urls:
            paths = download_urls(urls, args.output_dir)
            # v2.2.0 修复：未下载成功的 URL 警告只走 stderr，
            # **不**在 stdout 里输出无对应 PATH 的孤立 URL_2/URL_3
            # （避免 agent 误以为可以发图给主人）
            for u in urls[len(paths):]:
                print(f"# [warn] download failed for {u}", file=sys.stderr)
        _print_agent_success(paths, urls, args.prompt, payload["size"])
        # 下载全部失败时返非零退出码（API 成功但结果不可用）
        if urls and not paths:
            return 2
    else:
        # json / human 模式：保持 v2.0.1 行为（dump 完整响应 + "Downloaded:" 行）
        print(json.dumps(response, ensure_ascii=False, indent=2))
        if args.output_dir and urls:
            for path in download_urls(urls, args.output_dir):
                print(f"Downloaded: {path}")
        elif args.output_dir:
            print("No downloadable image URLs found in response.", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate images with Agnes Image 2.1 Flash.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate = subparsers.add_parser("generate", help="Submit an image generation request")
    generate.add_argument("--prompt", required=True)
    generate.add_argument("--size", default="1024x768")
    generate.add_argument("--image-url", action="append",
                          help="Reference image URL for image-to-image (must be a publicly accessible HTTPS URL, NOT a local file path). Repeatable for multiple references.")
    # v2.0.0: 删 --response-format（API 只支持 url，参数冗余）
    generate.add_argument("--output-dir", default="/home/goron/文档/Openclaw/输出/agnes-free-image",
                          help="Download returned image URLs into this directory")
    generate.add_argument("--api-base", default=API_BASE)
    generate.add_argument("--dry-run", action="store_true", help="Print request JSON without calling the API")
    generate.add_argument("--max-retries", type=int, default=MAX_RETRIES,
                          help=f"Max retry rounds (default {MAX_RETRIES})")
    # v2.1.0: 输出格式。默认 agent（AI agent 是主要消费者）
    generate.add_argument("--format", choices=["agent", "json", "human"], default="agent",
                          help="Output format: 'agent' (default) emits structured STATUS/PATH/URL on stdout for AI agent parsing; 'json' dumps full API response (errors to stderr); 'human' is alias of 'json'.")
    generate.set_defaults(func=cmd_generate)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
