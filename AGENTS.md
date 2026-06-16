# Repository Guidelines

## Project Structure & Module Organization

The runnable application lives in `src_gpt5.5/`. Core Python code is under `src_gpt5.5/app/`: `server.py` exposes HTTP APIs, `main.py` starts the service, `db.py` owns SQLite schema setup, and `config.py` loads runtime settings. Domain logic is in `src_gpt5.5/app/services/`, including crawling, Markdown parsing/import, text analysis, market data, and task scheduling. The local web UI is in `src_gpt5.5/app/web/`, with static assets in `app/web/static/`. Configuration is in `src_gpt5.5/config/app.json`. Runtime files such as SQLite databases, logs, PID files, and exports belong in `src_gpt5.5/data/`. Post Markdown content is stored outside the app code according to `paths.content_root`.

## Build, Test, and Development Commands

Run commands from `src_gpt5.5/`.

```powershell
python -m compileall app
node --check app\web\static\app.js
.\start_service.cmd
.\status_service.cmd
.\stop_service.cmd
```

`compileall` checks Python syntax. `node --check` validates frontend JavaScript syntax. Use `start_app.cmd` for foreground Windows runs, `start_service.cmd` for background service runs, and the `.sh` scripts for Linux/macOS.

## Coding Style & Naming Conventions

Use Python 3 standard-library patterns already present in the project. Prefer type hints, dataclasses for configuration/data containers, and small service functions. Keep paths platform-neutral with `pathlib.Path`; do not hardcode Windows or Linux absolute paths. JavaScript is plain browser JS, so avoid adding frameworks unless explicitly needed. Use concise names that match existing conventions, such as `api_*` handlers, `*_service.py` modules, and `render*` frontend functions.

## Testing Guidelines

There is no established test framework yet; `tests/` is currently empty. For every change, at minimum run Python compilation and JS syntax checks. For backend behavior, prefer focused script-based checks against service functions or temporary local API calls. Name future tests after the module or behavior, for example `tests/test_crawler_service.py`.

## Commit & Pull Request Guidelines

No Git history is available in this checkout, so use clear imperative commit messages such as `Add crawler progress logging` or `Fix content root path handling`. Pull requests should include a short problem summary, changed files or modules, verification commands, and screenshots for visible UI changes.

## Security & Configuration Tips

Do not commit `.env` files, API keys, SQLite databases, logs, downloaded attachments, or generated exports. Keep `OPENAI_API_KEY` in the environment. Configure Markdown output with `paths.content_root` or `TRUTH_CONTENT_ROOT`; keep runtime data in `src_gpt5.5/data/`.

---

# 仓库指南

## 项目结构与模块组织

可运行应用位于 `src_gpt5.5/`。核心 Python 代码在 `src_gpt5.5/app/`：`server.py` 提供 HTTP API，`main.py` 启动服务，`db.py` 负责 SQLite 表结构，`config.py` 加载运行配置。业务逻辑在 `src_gpt5.5/app/services/`，包括抓取、Markdown 解析/导入、文本分析、行情数据和任务调度。本地 Web UI 位于 `src_gpt5.5/app/web/`，静态资源在 `app/web/static/`。配置文件是 `src_gpt5.5/config/app.json`。SQLite、日志、PID、导出文件等运行时数据放在 `src_gpt5.5/data/`。贴文 Markdown 内容根据 `paths.content_root` 保存，不应混入应用代码目录。

## 构建、测试与开发命令

在 `src_gpt5.5/` 下运行：

```powershell
python -m compileall app
node --check app\web\static\app.js
.\start_service.cmd
.\status_service.cmd
.\stop_service.cmd
```

`compileall` 检查 Python 语法。`node --check` 检查前端 JavaScript 语法。Windows 前台运行使用 `start_app.cmd`，后台服务使用 `start_service.cmd`，Linux/macOS 使用对应 `.sh` 脚本。

## 代码风格与命名约定

沿用项目现有 Python 3 标准库风格。优先使用类型标注、dataclass 配置/数据结构和小型服务函数。路径处理使用 `pathlib.Path`，不要写死 Windows 或 Linux 绝对路径。前端是原生浏览器 JavaScript，除非明确需要，不要引入框架。命名保持现有习惯，例如 `api_*` 接口函数、`*_service.py` 服务模块和 `render*` 前端渲染函数。

## 测试指南

目前尚未建立正式测试框架，`tests/` 目录为空。每次改动至少运行 Python 编译检查和 JS 语法检查。后端行为建议用聚焦的小脚本或临时本地 API 调用验证。未来测试文件可按模块或行为命名，例如 `tests/test_crawler_service.py`。

## 提交与 Pull Request 指南

当前检出目录没有可参考的 Git 历史，因此建议使用清晰的祈使句提交信息，例如 `Add crawler progress logging` 或 `Fix content root path handling`。PR 应包含问题概述、涉及的文件或模块、验证命令；如果有可见 UI 改动，请附截图。

## 安全与配置建议

不要提交 `.env` 文件、API Key、SQLite 数据库、日志、下载附件或生成的导出文件。`OPENAI_API_KEY` 应放在环境变量中。Markdown 输出目录通过 `paths.content_root` 或 `TRUTH_CONTENT_ROOT` 配置；运行时数据保留在 `src_gpt5.5/data/`。
