# 贡献指南

感谢关注 bidking-booooot。参与前请阅读 [行为准则](CODE_OF_CONDUCT.md)。

## 流程

1. Fork 仓库，从 `main` 拉取最新代码
2. 新建分支（建议 `fix/...` 或 `feat/...`）
3. 提交 PR 到 `main`，填写 PR 模板中的测试与自检项

## 开发环境

```cmd
cd /d <repo_root>
python -m venv .venv
.\.venv\Scripts\activate
pip install -e .
```

首次运行前复制 `configs\config.json.example` 为 `configs\config.json`。

## 测试

```cmd
python -m pytest -q
```

## 提交

- 聚焦单一主题，避免混入个人 UID、对局 CSV、API 凭证
- 配置变更优先改 `configs/*.example` 或文档，勿提交 `configs/config.json`

## Issue / PR

- Bug 与功能建议请使用 GitHub Issue 模板（自动包含复现步骤、Python 版本等字段）
- PR 请使用仓库自带的 Pull Request 模板
- **勿**在 Issue/PR 中粘贴真实 UID、token、完整 `Player.log` 或他人对局数据

## 欢迎的贡献类型

- 文档与注释改进
- 测试用例与 Bug 修复
- `configs/*.example`、`data/` 静态表更新（遵循 `data/版本更新手册.md`）
- 地图出价参数 `configs/pricing.maps/`（可脱敏示例）

## 通常不合并

- 远程 Bot 门禁、腾讯文档黑名单同步、需上传/共享玩家数据的运营向功能（见 README「开源版不包含」）