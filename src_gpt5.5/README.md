# 特朗普真实社交贴文分析系统

这是第一版可运行实现，代码全部位于 `src_gpt5.5`。系统使用 Python 标准库提供本地 Web 应用、SQLite 数据库、后台任务、Markdown 导入、基础文本分析、OpenAI 大模型适配、每日抓取、附件下载、行情同步、回测和预测骨架。

## 运行方式

1. 在 PowerShell 中进入目录：

```powershell
cd src_gpt5.5
```

2. 可选：设置 OpenAI API Key：

```powershell
$env:OPENAI_API_KEY="你的 OpenAI API Key"
```

3. 启动服务：

```powershell
.\start_app.cmd
```

如果希望在后台启动并返回命令行：

```powershell
.\start_service.cmd
```

查看状态或停止后台服务：

```powershell
.\status_service.cmd
.\stop_service.cmd
```

Linux/macOS 下使用 Bash 脚本：

```bash
cd src_gpt5.5
chmod +x start_service.sh stop_service.sh status_service.sh service_common.sh
./start_service.sh
./status_service.sh
./stop_service.sh
```

4. 浏览器访问：

```text
http://127.0.0.1:8000
```

默认监听 `0.0.0.0:8000`，同一局域网内其他设备可通过本机 IP 访问。若开放局域网使用，建议只在可信网络中运行。

## 当前能力

- 扫描当前目录及子目录 Markdown 贴文。
- 排除需求文档和抓取进度文件。
- 解析标题、作者、发布时间、原始链接、status ID、来源、正文、附件。
- 写入 SQLite 并去重。
- 生成词频、国家、主题、中国相关性、情绪、美股相关信号。
- Web 页面查看仪表盘、贴文列表、详情、文本分析、股市分析、任务中心和配置。
- 支持 Web 手工触发抓取、导入、分析、行情同步、回测、预测。
- 后端运行时按北京时间自动触发每日任务。
- 抓取新增贴文时沿用当前年份/月度目录，并尝试下载附件。

## 重要说明

- 贴文 Markdown 保存根目录由 `config/app.json` 的 `paths.content_root` 控制，默认值为 `..`，即 `src_gpt5.5` 的上一级目录。抓取时会在该目录下按 `年份/月` 创建 Markdown，附件保存在对应月份目录下的 `attachments/{source_status_id}`。如果迁移到 Linux，只需要把 `content_root` 改成 Linux 上的目标目录，或设置环境变量 `TRUTH_CONTENT_ROOT`。
- SQLite 数据库、日志和导出文件默认仍放在 `src_gpt5.5/data`，不和贴文 Markdown 根目录混用。
- OpenAI 模型默认配置为 `gpt-5.5`，可在 `config/app.json` 中修改。
- 行情数据源先使用免账号的 Stooq 日线 CSV 适配器，后续可以替换为付费或更稳定的数据源。
- 美股相关性、回测和预测只用于研究，不构成投资建议。
- 内置调度器只有在服务进程运行时才会触发每日任务；如果希望电脑无人值守自动运行，应再配 Windows 任务计划程序启动 `start_app.ps1`。

## 常用任务

在 Web 的“任务中心”中可以手工触发：

- 抓取新增：从 `已抓取.md` 读取最大编号，继续扫描 `trumpstruth.org/statuses/{id}`。
- 导入 Markdown：将已有 Markdown 入库。
- 分析贴文：重新或增量生成文本分析。
- 同步行情：下载 SPY、QQQ、DIA 日线。
- 回测：基于贴文市场信号运行简单事件策略。
- 预测：生成研究性方向预测。
