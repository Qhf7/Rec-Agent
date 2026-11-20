# 贡献指南

欢迎通过 Issue 报告问题、讨论需求，或通过 Pull Request 提交改进。

## 本地开发

按[快速开始](README.md#快速开始)安装依赖，然后安装开发工具：

```bash
pip install pytest
```

在独立分支完成修改。提交前运行与改动相关的检查：

```bash
python3 -m pytest -q
node --test tests/static-api.test.js
python3 scripts/validate_data.py
```

前端静态接口检查需要 Node.js 18 或更高版本。模型联网调用使用开发者自己的环境变量凭据，常规自动化检查使用本地样例与冻结响应。

## 提交约定

- 说明具体问题、修改后的行为和验证方式；界面改动可附截图。
- 调整输入输出结构时，同步更新协议参考与样例。
- 用户与商品数据沿用[统一数据契约](data/README.md)。
- API 密钥放入进程环境；运行产物保存到已忽略的 `runs/` 目录。

## 报告问题

请提供运行环境、操作步骤、预期行为和实际结果。分享日志或 JSON 前，移除凭据及真实用户信息。
