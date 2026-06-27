#!/usr/bin/env python3
"""agnes-free-image v2.2.0 单元测试

覆盖纯函数（不依赖网络/环境变量）：
- is_quota_error: 配额关键词判断（含中文宽泛词误报修复验证）
- validate_size: 尺寸格式校验（含大写 X、中文 ×、None、空字符串）
- build_payload: T2I / I2I 请求体构造
- collect_urls: 嵌套 dict/list 里的 URL 提取
- filename_from_url: 各种 URL 形态的文件名生成
- _print_agent_success / _print_agent_error: agent 模式 stdout 输出
- is_agnes_cdn_url: Agnes 自带 CDN 直链判断

不测试 request_json_with_retry（依赖网络）和 get_api_keys（依赖环境变量），
那两个由 integration test 覆盖（在 OpenClaw 主会话手动跑）。

运行：
    cd skills/创作工具/agnes-free-image
    pytest tests/ -v
"""

from __future__ import annotations

import argparse
import contextlib
import io
import sys
from pathlib import Path

# 让 pytest 能找到 scripts/ 下的模块
SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from agnes_image import (  # noqa: E402
    _print_agent_error,
    _print_agent_success,
    build_payload,
    collect_urls,
    filename_from_url,
    is_agnes_cdn_url,
    is_quota_error,
    validate_size,
)


# ===========================================================================
# is_quota_error
# ===========================================================================

class TestIsQuotaError:
    """v2.2.0 修复点：中文宽泛词 '今天' / '建议您' / '升级权益' 不再误判"""

    def test_english_quota_kw(self):
        assert is_quota_error("quota exceeded", None) is True

    def test_english_rate_limit(self):
        assert is_quota_error("rate limit reached", None) is True

    def test_english_insufficient_quota(self):
        assert is_quota_error("Insufficient Quota, please upgrade", None) is True

    def test_chinese_strong_kw_次数已用完(self):
        assert is_quota_error("今日次数已用完", None) is True

    def test_chinese_strong_kw_配额已用完(self):
        assert is_quota_error("配额已用完，请升级", None) is True

    def test_chinese_strong_kw_已达上限(self):
        assert is_quota_error("已达调用上限", None) is True

    # --- v2.2.0 关键回归测试：中文宽泛词不能误判 ---

    def test_中文今天_不误判(self):
        """'今天是个好日子' 在 v2.1.x 会被误判，v2.2.0 必须 False"""
        assert is_quota_error("今天是个好日子", None) is False

    def test_中文建议您_不误判(self):
        """'建议您明天再来' 在 v2.1.x 会被误判，v2.2.0 必须 False"""
        assert is_quota_error("建议您明天再来", None) is False

    def test_中文升级权益_不误判(self):
        """'升级权益' 已从 v2.2.0 关键词列表移除"""
        assert is_quota_error("欢迎升级权益", None) is False

    def test_中文宽泛词组合_不误判(self):
        """多个宽泛词组合也不能误判"""
        assert is_quota_error("今天是个好日子，建议您明天再来", None) is False

    # --- 边界 case ---

    def test_empty_body(self):
        assert is_quota_error("", None) is False

    def test_none_body(self):
        assert is_quota_error(None, None) is False

    def test_normal_text(self):
        assert is_quota_error("hello world", None) is False

    def test_status_param_ignored(self):
        """is_quota_error 只看 body 文本，status 由调用方自行判断"""
        assert is_quota_error("quota exceeded", 401) is True
        assert is_quota_error("normal text", 401) is False


# ===========================================================================
# validate_size
# ===========================================================================

class TestValidateSize:
    """v2.2.0 改进：支持大写 X、中文 ×、None、空字符串

    v2.2.1 改进：函数现在返回规范化后的 size 字符串（保证 build_payload 发的就是 API 接受的格式）。
    之前 validate_size 只检查通过，但 build_payload 用原始 args.size，导致 1024X768 / 1024×768 被 API 拒绝。
    """

    def test_standard_format(self):
        assert validate_size("1024x768") == "1024x768"

    def test_uppercase_x(self):
        """v2.2.0 起支持 1024X768（用户友好），v2.2.1 起返回小写 x 形式"""
        assert validate_size("1024X768") == "1024x768"

    def test_chinese_x(self):
        """v2.2.0 起支持 1024×768（中文乘号），v2.2.1 起返回小写 x 形式"""
        assert validate_size("1024×768") == "1024x768"

    def test_square(self):
        validate_size("1024x1024")  # 不抛

    def test_small_size(self):
        validate_size("100x100")  # 不抛

    def test_4_digit(self):
        validate_size("4096x4096")  # 不抛

    def test_invalid_alpha(self):
        try:
            validate_size("abc")
        except SystemExit as e:
            assert "Invalid size" in str(e)
        else:
            raise AssertionError("validate_size('abc') should have raised SystemExit")

    def test_invalid_zero_width(self):
        try:
            validate_size("0x100")
        except SystemExit as e:
            assert "Invalid size" in str(e)
        else:
            raise AssertionError("validate_size('0x100') should have raised SystemExit")

    def test_invalid_incomplete(self):
        try:
            validate_size("1024x")
        except SystemExit as e:
            assert "Invalid size" in str(e)
        else:
            raise AssertionError("validate_size('1024x') should have raised SystemExit")

    def test_none_size(self):
        """v2.2.0 起 None 有专门错误信息"""
        try:
            validate_size(None)
        except SystemExit as e:
            assert "Missing --size" in str(e)
        else:
            raise AssertionError("validate_size(None) should have raised SystemExit")

    def test_empty_size(self):
        """v2.2.0 起空字符串也走 Missing 分支"""
        try:
            validate_size("")
        except SystemExit as e:
            assert "Missing --size" in str(e)
        else:
            raise AssertionError("validate_size('') should have raised SystemExit")

    def test_error_message_lists_common_sizes(self):
        """错误信息必须列出常见合法尺寸"""
        try:
            validate_size("abc")
        except SystemExit as e:
            msg = str(e)
            assert "1024x1024" in msg
            assert "1024x768" in msg
            assert "512x512" in msg
        else:
            raise AssertionError("should have raised SystemExit")


# ===========================================================================
# build_payload
# ===========================================================================

class TestBuildPayload:
    def test_t2i_payload(self):
        ns = argparse.Namespace(prompt="test prompt", size="1024x768", image_url=None)
        payload = build_payload(ns)
        assert payload["model"] == "agnes-image-2.1-flash"
        assert payload["prompt"] == "test prompt"
        assert payload["size"] == "1024x768"
        assert "extra_body" not in payload

    def test_t2i_uppercase_x_normalized(self):
        """v2.2.1 修复：1024X768 进 build_payload 后必须输出 1024x768（API 只接受小写 x）"""
        ns = argparse.Namespace(prompt="test", size="1024X768", image_url=None)
        payload = build_payload(ns)
        assert payload["size"] == "1024x768", f"expected lowercase x, got {payload['size']!r}"

    def test_t2i_chinese_x_normalized(self):
        """v2.2.1 修复：1024×768 进 build_payload 后必须输出 1024x768"""
        ns = argparse.Namespace(prompt="test", size="1024×768", image_url=None)
        payload = build_payload(ns)
        assert payload["size"] == "1024x768", f"expected lowercase x, got {payload['size']!r}"

    def test_i2i_single_url(self):
        ns = argparse.Namespace(
            prompt="transform this",
            size="1024x768",
            image_url=["https://x.com/i.png"],
        )
        payload = build_payload(ns)
        assert "extra_body" in payload
        assert payload["extra_body"]["image"] == ["https://x.com/i.png"]
        assert payload["extra_body"]["response_format"] == "url"

    def test_i2i_multiple_urls(self):
        ns = argparse.Namespace(
            prompt="combine these",
            size="1024x768",
            image_url=["https://a.com/1.png", "https://b.com/2.png", "https://c.com/3.png"],
        )
        payload = build_payload(ns)
        assert payload["extra_body"]["image"] == [
            "https://a.com/1.png",
            "https://b.com/2.png",
            "https://c.com/3.png",
        ]

    def test_validate_size_called(self):
        """build_payload 内部会调用 validate_size"""
        ns = argparse.Namespace(prompt="test", size="invalid", image_url=None)
        try:
            build_payload(ns)
        except SystemExit:
            pass  # 期望抛
        else:
            raise AssertionError("build_payload should validate size and exit on invalid")


# ===========================================================================
# collect_urls
# ===========================================================================

class TestCollectUrls:
    def test_simple_dict_with_url_key(self):
        data = {"url": "https://example.com/x.png"}
        assert collect_urls(data) == ["https://example.com/x.png"]

    def test_simple_dict_with_image_url_key(self):
        data = {"image_url": "https://example.com/y.jpg"}
        assert collect_urls(data) == ["https://example.com/y.jpg"]

    def test_nested_list_of_dicts(self):
        data = {
            "data": [
                {"url": "https://a.com/x.png"},
                {"image_url": "https://b.com/y.jpg"},
            ],
        }
        assert collect_urls(data) == ["https://a.com/x.png", "https://b.com/y.jpg"]

    def test_skip_non_http_urls(self):
        """只提取 http/https 开头的 URL，跳过 file://、相对路径等"""
        data = {
            "local": {"url": "/tmp/foo.png"},
            "remote": {"url": "https://x.com/foo.png"},
            "data_uri": {"image_url": "data:image/png;base64,xxx"},
        }
        assert collect_urls(data) == ["https://x.com/foo.png"]

    def test_empty_dict(self):
        assert collect_urls({}) == []

    def test_empty_list(self):
        assert collect_urls([]) == []

    def test_deeply_nested(self):
        data = {"a": {"b": {"c": [{"url": "https://x.com/deep.png"}]}}}
        assert collect_urls(data) == ["https://x.com/deep.png"]


# ===========================================================================
# filename_from_url
# ===========================================================================

class TestFilenameFromUrl:
    def test_with_extension(self):
        assert filename_from_url("https://x.com/a/b/foo.png", 1) == "foo.png"

    def test_no_extension(self):
        """无扩展名 fallback 到 agnes-image-{index:02d}.png"""
        assert filename_from_url("https://x.com/a/b/foo", 1) == "agnes-image-01.png"

    def test_root_url_no_path(self):
        """根 URL 无 path 时 fallback"""
        assert filename_from_url("https://x.com/", 1) == "agnes-image-01.png"

    def test_index_used_in_fallback(self):
        """fallback 时 index 必须参与（多图不冲突）"""
        assert filename_from_url("https://x.com/", 5) == "agnes-image-05.png"


# ===========================================================================
# _print_agent_success / _print_agent_error
# ===========================================================================

class TestAgentOutput:
    """验证 stdout 结构化输出 + v2.2.0 修复（孤立 URL 不再输出）"""

    def _capture_stdout(self, fn, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            fn(*args, **kwargs)
        return buf.getvalue()

    def test_success_single(self):
        out = self._capture_stdout(
            _print_agent_success,
            ["/a.png"], ["u1"], "test", "1024x768",
        )
        assert "STATUS: ok" in out
        assert "PATH: /a.png" in out
        assert "URL: u1" in out

    def test_success_multiple(self):
        out = self._capture_stdout(
            _print_agent_success,
            ["/a.png", "/b.png", "/c.png"], ["u1", "u2", "u3"], "test", "1024x768",
        )
        assert "PATH: /a.png" in out
        assert "PATH_2: /b.png" in out
        assert "PATH_3: /c.png" in out
        assert "URL: u1" in out
        assert "URL_2: u2" in out
        assert "URL_3: u3" in out

    def test_success_no_images(self):
        """API 成功但 urls 为空（极端情况）"""
        out = self._capture_stdout(
            _print_agent_success, [], [], "test", "1024x768",
        )
        assert "STATUS: ok" in out
        assert "PROMPT: test" in out
        assert "SIZE: 1024x768" in out
        assert "PATH:" not in out  # 不输出空 PATH
        assert "URL:" not in out

    def test_partial_download_failure_no_isolated_url(self):
        """v2.2.0 修复：部分下载失败时不要输出孤立的 URL_2"""
        out = self._capture_stdout(
            _print_agent_success,
            ["/a.png"], ["u1", "u2"], "test", "1024x768",
        )
        assert "STATUS: ok" in out
        assert "PATH: /a.png" in out
        assert "URL: u1" in out
        # 关键：URL_2 不能出现（paths 只有 1 个，urls 有 2 个）
        assert "URL_2" not in out
        assert "u2" not in out  # 失败 URL 应该在 stderr，不在 stdout

    def test_error_with_status(self):
        out = self._capture_stdout(_print_agent_error, "quota exhausted", 429)
        assert "STATUS: error" in out
        assert "HTTP_STATUS: 429" in out
        assert "REASON: quota exhausted" in out

    def test_error_no_status(self):
        out = self._capture_stdout(_print_agent_error, "bad request")
        assert "STATUS: error" in out
        assert "HTTP_STATUS:" not in out
        assert "REASON: bad request" in out

    def test_error_truncates_long_message(self):
        """超长 REASON 截断到 300 字符"""
        long_msg = "x" * 1000
        out = self._capture_stdout(_print_agent_error, long_msg, 500)
        # 找 REASON: 后面的内容
        reason_line = next(l for l in out.splitlines() if l.startswith("REASON:"))
        assert len(reason_line) <= len("REASON: ") + 300

    def test_error_first_line_only(self):
        """多行错误只取第一行"""
        out = self._capture_stdout(_print_agent_error, "line1\nline2\nline3", 500)
        reason_line = next(l for l in out.splitlines() if l.startswith("REASON:"))
        assert "line1" in reason_line
        assert "line2" not in reason_line
        assert "line3" not in reason_line


# ===========================================================================
# is_agnes_cdn_url（v2.1.1 changelog 承诺的辅助函数）
# ===========================================================================

class TestIsAgnesCdnUrl:
    def test_google_storage_url(self):
        """Agnes 用 GCS 存图"""
        assert is_agnes_cdn_url(
            "https://storage.googleapis.com/agnes-aigc/foo/bar/abc.png"
        ) is True

    def test_files_agnes_ai_url(self):
        """备用 CDN 域名"""
        assert is_agnes_cdn_url("https://files.agnes-ai.com/xxx.png") is True

    def test_platform_outputs_url(self):
        """v2.2.0 实测的主流 CDN（2026-06 验证）"""
        assert is_agnes_cdn_url(
            "https://platform-outputs.agnes-ai.space/images/text-to-image/2026/06/abc.png"
        ) is True

    def test_catbox_url(self):
        """catbox 不是 Agnes CDN"""
        assert is_agnes_cdn_url("https://catbox.moe/abc.png") is False

    def test_example_url(self):
        assert is_agnes_cdn_url("https://example.com/foo.png") is False

    def test_empty(self):
        assert is_agnes_cdn_url("") is False

    def test_none(self):
        assert is_agnes_cdn_url(None) is False

    def test_http_not_https(self):
        """Agnes CDN 是 https，http 视为不是"""
        assert is_agnes_cdn_url("http://storage.googleapis.com/agnes-aigc/x.png") is False

    def test_partial_match_not_enough(self):
        """只匹配 path 里偶然含 agnes-aigc 的 URL 也不算"""
        # 这个 URL 是别人 CDN 模拟的路径，prefix 不匹配
        assert is_agnes_cdn_url("https://evil.com/agnes-aigc/foo.png") is False