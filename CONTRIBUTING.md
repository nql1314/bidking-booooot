# 贡献指南

感谢关注 bidking-booooot。

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

请描述复现步骤、Python 版本、相关地图/策略配置（可脱敏）。
