# agnes-free-image

> 用 Agnes Image 2.1 Flash 免费生成图片（文生图 / 图生图）

## 功能

- **文生图**（text-to-image）：输入文字描述生成图片
- **图生图**（image-to-image）：输入图片 + 文字描述进行风格转换
- **本地图传**：支持本地图片上传到 catbox.moe（需代理）

## 触发词

免费图片、AI 出图、画一张、生成图片、image-to-image、agnes

## 安装

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env，填入 API Key
AGNES_API_KEY=sk-your-key-here
HTTP_PROXY=http://127.0.0.1:7897   # 本地图传必须走代理
```

## 快速开始

```bash
python3 scripts/agnes_image.py "一只可爱的猫咪"
python3 scripts/agnes_image.py "input.png" "转换成油画风格"
```

## 目录结构

```
agnes-free-image/
├── SKILL.md              # Skill 入口文档
├── Changelog.md          # 版本变更历史
├── scripts/
│   └── agnes_image.py    # 主脚本
├── lib/
│   └── http_client.py    # HTTP 客户端（curl 封装）
├── agents/               # Agent 配置
├── tests/                # 测试用例
└── references/           # 参考资料
```

## API 说明

- **API**：Agnes Image 2.1 Flash
- **配额**：与 agnes-free-video 共享同一 API key quota 池
- **并发注意**：多 Key 用逗号分隔 `AGNES_API_KEY=sk-a,sk-b`
- **本地图传**：catbox.moe 必须走代理（HTTP_PROXY）

## 版本

当前版本：2.2.1