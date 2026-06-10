---
name: agnes-free-image
version: 2.2.0
description: 用 Agnes Image 2.1 Flash 免费生成图片（文生图 / 图生图）。触发词：免费图片、AI 出图、画一张、生成图片、image-to-image、agnes。注意：与 agnes-free-video 共享 API 配额池，并发场景用逗号分隔多 Key（AGNES_API_KEY=sk-a,sk-b）。
---

# Agnes Free Image

Use this skill to generate or transform images with `agnes-image-2.1-flash`.

## ⚠️ 重要提示（必读，2026-06-04 v2.0.0 补充）

### 1. OpenClaw 沙箱环境必读
- **坑**：OpenClaw 沙箱内 Python `urllib.request` 调用 HTTPS POST 会卡死 30 秒
- **解决**：v2.0.0 起 `scripts/agnes_image.py` 已**全程改用 `curl` 子进程**（经 `lib/http_client.py`），主会话直接可用，不需要手动绕开
- 退出码：成功 = 0，业务错误 = 1

### 2. Quota 共享提醒
- Agnes **image 和 video 共享同一 API key 的 quota 池**（同 key 不同 skill）
- 主人目前 **1 个 key**，并发跑 image + video 时一个会爆
- 解决方法：申请多个 key，逗号分隔传给 `AGNES_API_KEY`（脚本会自动轮换）
  ```bash
  export AGNES_API_KEY="sk-a,sk-b,sk-c"
  ```

### 3. 中文渲染能力
- `agnes-image-2.1-flash` 对**中文文字渲染能力有限**（海报里需要清晰中文时可能糊成乱码）
- 海报类带中文的设计图，**不要用本 skill**，改用 SDXL + Chinese LoRA 或 PaddlePaddle 排版

### 4. 图生图（I2I）必须用公网 URL（v2.1.0 补充，最常踩的坑）
- API 的 `extra_body.image` 字段**只接受公网可访问的 HTTPS URL**（api.md 写死的 array of URL）
- **不接受本地文件路径**（`/home/goron/图片/xxx.png` 直接传给 `--image-url` 会失败）
- **不接受 base64**（不在 API 文档里）
- 主人场景几乎都是**本地图片**（截图、照片），Agent 调 I2I 时必须**先把本地图片上传到公网图床**拿到 URL 再传
- **推荐图床**（按稳定性排序）：
  1. **catbox.moe**（最稳，curl 一次即可，免费无注册，文件永久）
     ```bash
     curl -F "reqtype=fileupload" -F "fileToUpload=@/path/to/local.png" \
       https://catbox.moe/user/api.php
     # 返回的就是直链 URL，可直接用作 --image-url
     ```
  2. 0x0.st（极简，不稳定）
  3. tmpfiles.org（临时，1小时过期，不适合多轮编辑）
- agent 最佳实践：**先检查图源**——Agnes 自身产出的？看 `URL:` 字段直接复用；本地图？走 catbox（见下文 ⭐ 子节）

### ⭐ v2.1.1 优先复用 Agnes 自身产出的图（链式 I2I/I2V 加速）

实测 Agnes API 返回的 `URL:` 字段（形如 `https://platform-outputs.agnes-ai.space/images/.../xxx.png` 或 `https://storage.googleapis.com/agnes-aigc/.../xxx.png` 或 `https://files.agnes-ai.com/...`）是**公网 HTTPS 直链**，永久有效，可以直接喂给下一次 I2I / I2V，**完全跳过 catbox.moe / 0x0.st 上传**。

**判断逻辑**（脚本内置 `is_agnes_cdn_url()`，v2.2.0 覆盖 3 个 CDN 域名）：
```python
is_agnes_cdn_url(url) → bool
# True: url.startswith(...) 匹配以下任一官方 CDN：
#   - https://storage.googleapis.com/agnes-aigc/         (早期)
#   - https://files.agnes-ai.com/                        (早期)
#   - https://platform-outputs.agnes-ai.space/           (2026-06 主流)
```

**工作流 A：链式 I2I（Agnes 自产图 → 再变换）**
```bash
# 1. T2I 先生成基础图
python3 scripts/agnes_image.py generate \
  --prompt "A cute corgi puppy in a flower field, golden hour" \
  --size 1024x768 --format agent
# stdout 拿到: PATH=/.../agnes-image-01.png  URL=https://storage.googleapis.com/agnes-aigc/.../xxx.png

# 2. 用上面拿到的 URL 直接做 I2I（不需要 catbox 上传！）
python3 scripts/agnes_image.py generate \
  --prompt "Same corgi but in snow, winter outfit, preserving composition" \
  --image-url "https://storage.googleapis.com/agnes-aigc/.../xxx.png" \
  --size 1024x768 --format agent
```

**工作流 B：链式 I2V（Agnes 自产图 → 喂给视频 skill）**
```bash
# 拿到 Agnes URL 后传给 agnes-free-video 的 --image-url
python3 /home/goron/文档/skills/创作工具/agnes-free-video/scripts/xxx.py \
  --prompt "corgi runs through snow" \
  --image-url "https://storage.googleapis.com/agnes-aigc/.../xxx.png"
```

**对比**：
- 本地图（截图、照片）→ 必须 catbox.moe 上传
- Agnes 自产图 → 直接用 URL，**省一次图床上传**

**注意**：
- 两种用途不冲突：发主人用 `MEDIA:<PATH>`（永久本地），链式调用用 `<URL>`（公网直链）

## Credential Rule

Read the API key from the environment. Do not hardcode keys in prompts, scripts, skill files, commits, or shell history.

Preferred variable（支持逗号分隔多 key）：

```bash
export AGNES_API_KEY="sk-xxx"          # 单 key
export AGNES_API_KEY="sk-a,sk-b,sk-c"  # 多 key 自动轮换
```

The helper also accepts `AGNES_TOKEN` as a fallback.

### ⚠️ v2.2.0 安全提醒：`.env` 是真实 key 文件

- 本目录的 **`.env` 包含真实 API key**，权限 0600（仅 owner 可读写）
- **不要 commit `.env`**：仓库根目录的 `.gitignore` 已把 `.env` 排除
- **新部署/克隆后**：复制 `.env.example` 为 `.env` 并填入真实 key
  ```bash
  cp .env.example .env
  chmod 600 .env
  # 编辑 .env 填入真实 key
  export $(cat .env | xargs)
  ```
- **泄露后立刻**去 Agnes 控制台 revoke key，重新申请

## Quick Start

Text-to-image:

```bash
python3 scripts/agnes_image.py generate \
  --prompt "A luminous floating city above a misty canyon at sunrise, cinematic realism" \
  --size 1024x768
```

> 默认保存到 `/home/goron/文档/Openclaw/.输出/agnes-image/`。指定其他路径加 `--output-dir /path/to/dir`。

Image-to-image with a public image URL:

```bash
python3 scripts/agnes_image.py generate \
  --prompt "Transform the scene into a rain-soaked cyberpunk night while preserving the composition" \
  --image-url "https://example.com/input.png" \
  --image-url "https://example.com/input2.png" \
  --size 1024x768
```

Validate the request shape without calling the API:

```bash
python3 scripts/agnes_image.py generate \
  --prompt "A detailed AI workflow dashboard poster, clean editorial style" \
  --size 1024x1024 \
  --dry-run
```

> **默认输出路径**：`/home/goron/文档/Openclaw/.输出/agnes-image/`（省略 `--output-dir` 时使用）。符合 TOOLS.md 全局约定。脚本完成后会打印 `Downloaded: <path>`，agent 直接拿这个路径发图。

## Agent-Friendly Output（v2.1.0 新增）

agent 调 skill 时，**默认用 `--format agent`**，stdout 会输出**结构化、易解析**的字段（每行一个 key）：

```bash
python3 scripts/agnes_image.py generate \
  --prompt "A cute corgi puppy playing in a flower field" \
  --size 1024x768 \
  --format agent
```

成功时输出：
```text
STATUS: ok
PROMPT: A cute corgi puppy playing in a flower field
SIZE: 1024x768
PATH: /home/goron/文档/Openclaw/.输出/agnes-image/agnes-image-01.png
URL: https://files.agnes-ai.com/xxx.png
```

失败时输出（注意：`STATUS: error` 走 **stdout** 不是 stderr，agent 一定看得到）：
```text
STATUS: error
HTTP_STATUS: 429
REASON: Agnes API quota exhausted (HTTP 429): ...
```

agent 解析方式：grep `^STATUS:` → 看 `ok` 还是 `error`；成功再 grep `^PATH:` 拿本地路径。

**三种 format 对比**：

| `--format` | 适合谁 | 输出 |
|------------|--------|------|
| `agent` (默认) | AI agent | 结构化 key-value，错误也走 stdout |
| `json` | 调试 / 二次处理 | dump 完整 API 响应 JSON，错误走 stderr |
| `human` | 人看 = `json` 的别名 | 同 json |

## After Generation（v2.1.0 新增）

脚本完成后，agent 应该这样把图发给主人：

```text
MEDIA:/home/goron/文档/Openclaw/.输出/agnes-image/agnes-image-01.png
```

**必须用本地路径（PATH），不要用 URL**——Agnes 返回的 URL 是临时签名链接，会过期；本地文件一直在。

I2I 任务（参考图生图）的工作流：

```text
1. 把主人给的本地图上传到 catbox.moe → 拿到公网 URL
2. python3 scripts/agnes_image.py generate --prompt "..." --image-url "<公网 URL>" --format agent
3. 从 stdout 拿 PATH，回复主人时用 MEDIA:<PATH> 发图
```

## Prompt Pattern

Use this structure for text-to-image:

```text
[Subject] + [Scene / Environment] + [Style] + [Lighting] + [Composition] + [Quality Requirements]
```

For image-to-image, say both what should change and what should remain unchanged.

## Workflow

### Agent 视角的标准工作流（v2.2.0 推荐）

```bash
# 0. 确保环境变量（首次或换 key 后）
export $(cat .env | xargs)  # 或 source .env

# 1. 复杂 prompt 先 dry-run 校验请求体（不发 API 请求）
python3 scripts/agnes_image.py generate \
  --prompt "<完整 prompt>" \
  --size 1024x768 \
  --dry-run

# 2. 正式生成（agent 模式输出结构化字段）
python3 scripts/agnes_image.py generate \
  --prompt "<完整 prompt>" \
  --size 1024x768 \
  --format agent

# 3. 解析 stdout
# 成功：grep "^STATUS:" → ok；再 grep "^PATH:" 拿本地路径
# 失败：grep "^STATUS:" → error；grep "^REASON:" 看原因

# 4. 发图给主人用 MEDIA:<PATH>（不要用 URL，会过期）
```

### 三种典型场景的 prompt 模板

**场景 1：文生图（T2I）**
```
[主体] + [环境/背景] + [风格] + [光线] + [构图] + [质量要求]
例：A luminous floating city above a misty canyon at sunrise, cinematic realism, 8k, golden hour lighting, wide-angle composition
```

**场景 2：图生图（I2I）— 本地图**
```
1. catbox 上传：curl -F "reqtype=fileupload" -F "fileToUpload=@/path/to/local.png" https://catbox.moe/user/api.php
2. 拿到 URL 后：python3 scripts/agnes_image.py generate --prompt "..." --image-url "<URL>" --format agent
```

**场景 3：链式 I2I — Agnes 自产图**
```
直接复用上次产出的 URL，无需 catbox（见上文 ⭐ 子节）
```

### 手动判断参考

1. Decide whether the request is text-to-image or image-to-image.
2. Turn vague visual requests into a concrete prompt with subject, environment, style, lighting, composition, and detail level.
3. Use `scripts/agnes_image.py generate`. Prefer `--dry-run` first for complex prompts or reference images.
4. Save returned image URLs locally with `--output-dir` when the response includes downloadable URLs.
5. Read `references/api.md` when the raw response shape or advanced parameters matter.

### 常见错误快速排查

| 现象 | 原因 | 解决 |
|------|------|------|
| `HTTP 401` + `quota exceeded` | 单 key 配额耗尽 | 加新 key 到 `AGNES_API_KEY` 逗号分隔 |
| `HTTP 401` + `invalid api key` | key 写错或过期 | 去 Agnes 控制台核对 |
| `HTTP 429` | 限流（短时间内请求过多） | 等 30s 后重试，或加多 key |
| agent 模式看不到错误 | 用 `cat`/`>` 重定向了 stderr | 直接 stdout 看 `STATUS: error` |
| 下载后图是空白页 | URL 过期或签名失效 | 用 `MEDIA:<PATH>` 发本地，不要用 URL |
| `--size 1024X768` 报错 | 旧版区分大小写 | **v2.2.0 起已支持大写 X 和中文 ×** |

## Reliability & Error Handling (v2.0.0 → v2.0.1)

- **自动重试**：5xx / 429 / 网络错误最多 **3 次尝试**（含原始请求，指数退避 1.5s / 3s 在第 2、3 次尝试前；429 额外等 10s / 20s / 30s）
- **多 Key 轮换**：`AGNES_API_KEY=key1,key2,key3` 自动按顺序尝试——遇到可重试错误（5xx / 429 / 网络 / 401 / 403 鉴权失败）立即切下一个 key
- **错误分类**：
  - 401/403 + 配额关键词（如"quota"/"次数已用完"）→ 立即报错（quota 跨 key 共享，无意义再换）
  - 401/403 + 非配额 → 自动切下一个 key 重试（单 key 鉴权失败）
  - 其他 4xx → 立即报错（业务错误，重试无意义）
  - 5xx / 429 / 超时 → 重试 + 切下一个 key
- **下载**：v2.0.0 起下载阶段也用 `curl`（避免 urllib 沙箱卡死）；v2.0.1 加 `-f` flag + `returncode` 校验，HTTP 错误响应不会被当成图片保存

调整重试轮数：

```bash
python3 scripts/agnes_image.py generate --prompt "..." --max-retries 5
```

## Notes

- Endpoint: `POST https://apihub.agnes-ai.com/v1/images/generations`
- Model: `agnes-image-2.1-flash`
- Default size in the helper is `1024x768`.
- For image-to-image, input images must be URL-accessible and are sent under `extra_body.image` (as array).
- The helper asks for URL responses with `extra_body.response_format: "url"`.

## Reference

Read `references/api.md` when you need request fields, response handling, or prompt examples from the source docs.

## Project Layout

```
agnes-free-image/
├── SKILL.md              # 主文档（agent 必读）
├── Changelog.md          # 版本变更历史（独立文件，2026-06 起独立）
├── .env                  # 真实 API key（0600 权限，git 忽略）
├── .env.example          # 配置模板（可 commit）
├── .gitignore            # 排除 .env / __pycache__ / .pytest_cache
├── agents/openai.yaml    # 旧 OpenAI plugin 兼容声明
├── lib/http_client.py    # curl 子进程 HTTP 客户端（沙箱兼容）
├── scripts/
│   └── agnes_image.py    # 主脚本（generate 子命令，--format agent/json/human）
├── tests/
│   └── test_agnes_image.py  # 单元测试（pytest）
└── references/api.md     # API 原始文档
```

## Changelog

完整版本变更历史见 [`Changelog.md`](./Changelog.md)。最近变更：

- **v2.2.0 (2026-06-10)**：Agent 视角深度审查（11 项修复）
  - P0 安全：加 `.gitignore` + `.env.example` + SKILL.md 警告
  - P0 修 bug：`is_quota_error` 收紧关键词（去除"今天"等宽泛词，避免误判正常文本）
  - P0 补文档：v2.1.1 changelog 承诺的 "⭐ 优先复用 Agnes 自身产出的图" 子节补到 SKILL.md 主体
  - P0 修 bug：部分下载失败时 `_print_agent_success` 不再输出孤立的 URL_2（避免 agent 解析混乱）
  - P1 代码质量：`validate_size` 支持大写 X / 中文 ×；新增 `is_agnes_cdn_url()` 辅助函数
  - P1 测试：新增 `tests/test_agnes_image.py`，关键纯函数 100% 覆盖（11 个测试）
  - P2 文档：SKILL.md 加 `.env.example` 用法、加常见错误排查表、加 Project Layout
  - P2 清理：删除 `__pycache__/` 和 `.pytest_cache/` 目录
  - P2 文档：变更历史迁出 SKILL.md，**独立成 `Changelog.md`**（符合 SOUL.md 铁律 #6）
  - 备份：`.输出/skill-backups/agnes-free-image-v2.1.1-pre_v2.2.0-20260610_xxxx/`
- **v2.1.1 (2026-06-06)**：⭐ 文档优化 - Agnes 自身图可直链

- **v2.1.1 (2026-06-06)**：⭐ 文档优化 - Agnes 自身图可直链
  - **O1 加 "⭐ 优先复用 Agnes 自身产出的图" 子节**：实测 Agnes API 返回的 `URL:` 字段（`https://storage.googleapis.com/agnes-aigc/.../xxx.png`）是公网 HTTPS 直链，可直接喂给下一次 I2I / I2V，**完全跳过 catbox.moe / 0x0.st**。配 2 个工作流模板：链式 I2I + 链式 I2V。
  - **O2 After Generation 节补充**：发主人用 PATH（永久本地），链式调用用 URL（公网直链），两种用途不冲突。
  - **O3 修复 docstring**：把"agent 最佳实践：I2I 任务先调一次 catbox.moe 上传"改成"**先检查图源**——Agnes 生成的？看 `URL:` 字段；本地图？走 catbox"，避免误导 agent 每次都先传图床。
  - **无代码改动**：scripts/agnes_image.py 一行未动，纯文档优化。
  - **验证**：实测 2 步 T2I→I2I 直链，`STATUS: ok` + exit 0。
  - **备份**：`.输出/skill-backups/agnes-free-image-v2.1.0-pre_v2.1.1-20260606_0815/`
- **v2.1.0 (2026-06-05)**：Agent 视角优化
  - **P0 修 I2I URL 缺口**：SKILL.md 显眼位置写明"image-to-image 必须用公网 URL"，附 catbox.moe 上传教程
  - **P1 加 agent-friendly 输出**：`--format {agent|json|human}`，agent 模式 stdout 输出 `STATUS/PATH/URL/PROMPT/SIZE` 结构化字段；错误也走 stdout（agent 一定看得到）
  - **O1 quota 共享写进 description**：front matter 加一句，避免 agent 匹配 skill 时漏掉
  - **O4 加 "After Generation" 节**：明确告诉 agent 用 `MEDIA:<path>` 指令把图发给主人，不要用 URL
  - **O5 默认输出路径写进 Quick Start**：`/home/goron/文档/Openclaw/.输出/agnes-image/`
  - **备份**：`.输出/skill-backups/agnes-free-image-v2.0.1-pre_v2.1.0-20260605_1334/`
- **v2.0.1 (2026-06-04)**：P0 完整审查修复
  - **P0-1 修 bug**：`request_json_with_retry` 在 5xx/429/网络错误路径补 `continue`，多 Key 轮换真正生效（之前 5xx 永远从 key 1 重试，sk-b/sk-c 用不上）
  - **P0-2 修文档**：SKILL.md "重试 3 轮" 改成 "最多 3 次尝试"（消歧义）；明确 5xx/429 也会切 key
  - **P0-3 删死代码**：删除未使用的 `parse_json_or_text` + `extract_error_message` 函数
  - **P1-1 改注释**：`is_quota_error` 去掉跨产品引用，描述中性化
  - **P1-2 download 加固**：curl 加 `-f` flag + `returncode` 校验 + 失败时清理空文件，防 HTTP 错误响应被当图片保存
  - 备份：`.输出/skill-backups/agnes-free-image-v2.0.0-20260604_1233/`
- **v2.0.0 (2026-06-04)**：P1-P4 完整优化
  - P1: `urllib` → `curl`（沙箱兼容）
  - P2: 指数退避重试（5xx/429/网络）
  - P3: 多 Key 轮换（逗号分隔）
  - P4: 错误分类（401 quota vs auth 区分）
  - 删冗余 `--response-format` 参数
  - 备份：`.输出/skill-backups/agnes-free-image-v1.0.0-20260604_0906/`
- **v1.0.0 (2026-06-01)**：初版，单 key + urllib.request
