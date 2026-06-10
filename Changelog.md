# Changelog — agnes-free-image

> 完整版本变更历史。SKILL.md 只列最近变更摘要，详细见本文档。

## v2.2.0 (2026-06-10) — Agent 视角深度审查

**性质**：11 项 P0/P1/P2 修复 + 独立 Changelog。无破坏性变更，向后兼容 v2.1.x。

### P0 安全
- **加 `.gitignore`**：排除 `.env`、`__pycache__/`、`.pytest_cache/`、`.pytest_cache/.gitignore` 之外的所有缓存/调试文件
- **创建 `.env.example`**：作为配置模板（不含真实 key，可 commit）
- **SKILL.md 加安全警告节**：提醒 `.env` 含真实 key，不要 commit，泄露后立刻 revoke

### P0 正确性 bug 修复
- **`is_quota_error` 关键词收紧**：
  - **移除** 过于宽泛的 "今天"、"建议您"、"升级权益"（v2.1.x 容易误判 "今天是个好日子，建议您明天再来" 为配额错误）
  - **新增** 强相关关键词：`insufficient quota`、`credit exhausted`、`balance exhausted`、`配额已用完`、`额度已用完`、`已达上限` 等
  - 验证：之前误判率 100% → 修复后 0%
- **SKILL.md 主体补 v2.1.1 changelog 承诺的子节**：v2.1.1 changelog 说加了 "⭐ 优先复用 Agnes 自身产出的图" 子节并配 2 个工作流模板，但 SKILL.md 主体只字未提，本次补全（含 `is_agnes_cdn_url()` 判断逻辑、工作流 A 链式 I2I、工作流 B 链式 I2V）
- **`_print_agent_success` 部分下载失败逻辑修复**：
  - 之前：paths=[/a.png], urls=[u1, u2] 会输出 `PATH: /a.png / URL: u1 / URL_2: u2` —— 出现孤立 URL 让 agent 困惑（拿到 URL 但没本地路径）
  - 修复：只输出成对的 PATH_i/URL_i，孤立 URL 走 stderr 警告
  - **不破坏向后兼容**：多图全成功场景输出格式不变

### P1 代码质量
- **`validate_size` 用户友好化**：
  - 支持 `1024X768`（大写 X）
  - 支持 `1024×768`（中文 ×）
  - 改进错误提示：列出常见合法尺寸
- **新增 `is_agnes_cdn_url(url)` 辅助函数**：判断是否为 Agnes 自带 CDN 直链（用于链式 I2I 工作流）
  - v2.2.0 覆盖 3 个官方 CDN：`storage.googleapis.com/agnes-aigc/` / `files.agnes-ai.com/` / `platform-outputs.agnes-ai.space/`（最后一个是 2026-06 实测主流，v2.1.1 漏判）
- **新增单元测试 `tests/test_agnes_image.py`**：
  - 覆盖 `is_quota_error`（含 11 个边界 case，含中文宽泛词回归测试）
  - 覆盖 `validate_size`（含 11 个 case，含大写 X、中文 ×、None、空字符串）
  - 覆盖 `build_payload`（T2I + I2I，含 size 校验触发）
  - 覆盖 `collect_urls`（嵌套 dict + list，含 file:// / data: 跳过）
  - 覆盖 `filename_from_url`（4 种 URL 形态）
  - 覆盖 `_print_agent_success` / `_print_agent_error`（含 8 个 case，含部分下载失败、长消息截断、多行只取第一行）
  - 覆盖 `is_agnes_cdn_url`（含 9 种 URL，含 3 个 Agnes CDN 域名、evil.com 路径伪装）
  - **57 个测试全过**

### P2 文档 / Hygiene
- **SKILL.md Workflow 节重写**：加 Agent 视角标准工作流（dry-run → generate → parse → send）+ 三种典型场景 prompt 模板
- **SKILL.md 加 "常见错误快速排查" 表**：401 quota / 401 invalid / 429 / 看不到错误 / 图是空白页 / size 大小写 6 个常见问题
- **SKILL.md 加 Project Layout**：清晰展示项目结构
- **变更历史迁出 SKILL.md**：**独立成 `Changelog.md`**（符合 SOUL.md 铁律 #6）

### 清理
- 删除 `scripts/__pycache__/` 和 `.pytest_cache/` 目录

### 备份
- `.输出/skill-backups/agnes-free-image-v2.1.1-pre_v2.2.0-20260610_xxxx/`

### 验证
- `python3 -c "import ast; ast.parse(...)"` 三个核心脚本（`scripts/agnes_image.py` / `lib/http_client.py` / `tests/test_agnes_image.py`）语法 OK
- `pytest tests/` **57/57 全过**
- `python3 scripts/agnes_image.py generate --prompt "test" --dry-run` 输出合法 JSON 请求体
- 真实 API 端到端：生成 corgi puppy 图，`STATUS: ok` + PATH/URL 在 stdout
- 实测发现 API 主用 CDN 是 `platform-outputs.agnes-ai.space/`，v2.1.1 漏判 → v2.2.0 补上

---

## v2.1.1 (2026-06-06) — 文档优化：Agnes 自身图可直链

- **O1 加 "⭐ 优先复用 Agnes 自身产出的图" 子节**（**注**：v2.1.1 changelog 承诺加了，但 SKILL.md 主体缺失，v2.2.0 已补全）：实测 Agnes API 返回的 `URL:` 字段（`https://platform-outputs.agnes-ai.space/.../xxx.png` 或 `https://storage.googleapis.com/agnes-aigc/.../xxx.png`）是公网 HTTPS 直链，可直接喂给下一次 I2I / I2V，完全跳过 catbox.moe / 0x0.st
- **O2 After Generation 节补充**：发主人用 PATH（永久本地），链式调用用 URL（公网直链），两种用途不冲突
- **O3 修复 docstring**：把 "agent 最佳实践：I2I 任务先调一次 catbox.moe 上传" 改成 "先检查图源——Agnes 生成的？看 `URL:` 字段；本地图？走 catbox"
- **无代码改动**：scripts/agnes_image.py 一行未动，纯文档优化
- **验证**：实测 2 步 T2I→I2I 直链，`STATUS: ok` + exit 0
- **备份**：`.输出/skill-backups/agnes-free-image-v2.1.0-pre_v2.1.1-20260606_0815/`

---

## v2.1.0 (2026-06-05) — Agent 视角优化

- **P0 修 I2I URL 缺口**：SKILL.md 显眼位置写明 "image-to-image 必须用公网 URL"，附 catbox.moe 上传教程
- **P1 加 agent-friendly 输出**：`--format {agent|json|human}`，agent 模式 stdout 输出 `STATUS/PATH/URL/PROMPT/SIZE` 结构化字段；错误也走 stdout（agent 一定看得到）
- **O1 quota 共享写进 description**：front matter 加一句，避免 agent 匹配 skill 时漏掉
- **O4 加 "After Generation" 节**：明确告诉 agent 用 `MEDIA:<path>` 指令把图发给主人，不要用 URL
- **O5 默认输出路径写进 Quick Start**：`/home/goron/文档/Openclaw/.输出/agnes-image/`
- **备份**：`.输出/skill-backups/agnes-free-image-v2.0.1-pre_v2.1.0-20260605_1334/`

---

## v2.0.1 (2026-06-04) — P0 完整审查修复

- **P0-1 修 bug**：`request_json_with_retry` 在 5xx/429/网络错误路径补 `continue`，多 Key 轮换真正生效（之前 5xx 永远从 key 1 重试，sk-b/sk-c 用不上）
- **P0-2 修文档**：SKILL.md "重试 3 轮" 改成 "最多 3 次尝试"（消歧义）；明确 5xx/429 也会切 key
- **P0-3 删死代码**：删除未使用的 `parse_json_or_text` + `extract_error_message` 函数
- **P1-1 改注释**：`is_quota_error` 去掉跨产品引用，描述中性化
- **P1-2 download 加固**：curl 加 `-f` flag + `returncode` 校验 + 失败时清理空文件，防 HTTP 错误响应被当图片保存
- **备份**：`.输出/skill-backups/agnes-free-image-v2.0.0-20260604_1233/`

---

## v2.0.0 (2026-06-04) — P1-P4 完整优化

- **P1**：`urllib` → `curl`（沙箱兼容，OpenClaw 沙箱内 `urllib.request` 调用 HTTPS POST 会卡死 30 秒）
- **P2**：指数退避重试（5xx/429/网络错误重试 3 次，429 等更久）
- **P3**：多 Key 轮换（`AGNES_API_KEY` 逗号分隔，1 key 也兼容）
- **P4**：错误处理更细：区分 4xx 不重试、5xx/超时/网络/429 才重试
- 删冗余 `--response-format` 参数（API 只支持 url）
- **备份**：`.输出/skill-backups/agnes-free-image-v1.0.0-20260604_0906/`

---

## v1.0.0 (2026-06-01) — 初版

- 单 key + `urllib.request`
- T2I + I2I（基本功能）
- 无重试、无 agent-friendly 输出