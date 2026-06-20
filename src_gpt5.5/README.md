# 特朗普真实社交贴文分析系统

这是一个运行在本地的 Truth Social 贴文抓取与分析系统，主要用于：

- 抓取 `trumpstruth.org` 上的贴文
- 保存为 Obsidian 友好的 Markdown
- 导入 SQLite 做检索和统计
- 计算中国相关性、情绪、主题、实体、市场信号
- 提供一个本地 Web 界面查看、筛选和重分析数据

系统代码位于 `src_gpt5.5`，整体依赖尽量保持轻量，核心实现主要使用 Python 标准库。

## 功能概览

- 抓取新增贴文并保存为 Markdown
- 下载附件到本地
- 可选生成中文翻译
- 导入已有 Markdown 到 SQLite
- 贴文分析：主题、实体、情绪、中国相关性、市场信号
- 本地 Web 页面：仪表盘、贴文列表、详情页、分析页、任务中心、配置页
- 任务中心支持手工触发抓取、导入、分析、重分析、行情同步、回测、预测
- 内置每日定时任务：
  - 每日抓取
  - 每日行情同步

## 目录说明

- `app/`：后端代码
- `app/web/`：前端页面
- `config/app.json`：主配置文件
- `data/`：数据库、导出文件
- `logs/`：应用日志
- `start.ps1` / `stop.ps1` / `status.ps1`：Windows 启停脚本
- `start.sh` / `stop.sh` / `status.sh`：Linux 启停脚本
- `service_common.sh`：Linux 公共函数

## 运行环境

建议环境：

- Python 3.10+
- Windows 10/11 或 Linux
- 浏览器
- 可选：`OPENAI_API_KEY`

## 配置说明

主配置文件是 `config/app.json`，常用配置如下：

- `app.host`：监听地址
- `app.port`：监听端口
- `app.timezone`：时区
- `paths.content_root`：贴文 Markdown 的根目录
- `crawler.progress_file`：已抓取进度文件，默认在 `data/已抓取.md`
- `crawler.daily_time`：每日抓取时间
- `crawler.download_attachments`：是否下载附件
- `crawler.translate_to_chinese`：是否生成中文翻译
- `analysis.enable_llm`：是否启用大模型分析
- `analysis.openai_model`：大模型名称
- `analysis.china_relevance_*`：中国相关性判定规则
- `market.daily_sync_time`：每日行情同步时间
- `scheduler.enabled`：是否启用调度器
- `scheduler.run_on_startup`：启动后是否自动跑一次每日链路

### 中国相关性配置

目前中国相关性是可配置的，主要参数：

- `analysis.china_relevance_keywords`
- `analysis.china_relevance_excluded_keywords`
- `analysis.china_relevance_min_keyword_hits`
- `analysis.china_relevance_min_score`

它们控制的是：

- 哪些词算“相关”
- 哪些词明确排除
- 至少命中几个词才算
- 最低分数门槛是多少

当前匹配规则是：

- 忽略大小写
- 使用全词匹配
- 像 `xi` 只会匹配独立单词 `Xi`，不会匹配 `taxi` 之类的子串

## 启动方式

### Windows

直接启动前台服务：

```powershell
.\start.ps1
```

双击兼容入口：

```text
start.cmd
```

### Linux

```bash
chmod +x start.sh stop.sh status.sh service_common.sh
./start.sh
```

## 停止与状态

### Windows

```powershell
.\status.ps1
.\stop.ps1
```

或双击兼容入口：

```text
status.cmd
stop.cmd
```

### Linux

```bash
./status.sh
./stop.sh
```

## 浏览器访问

默认访问地址：

```text
http://127.0.0.1:8000
```

如果监听地址是 `0.0.0.0`，同一局域网内其他设备也可以通过本机 IP 访问。

## 部署说明

### 1. 准备目录

建议保持项目目录结构不变。默认情况下：

- 数据库放在 `src_gpt5.5/data/app.sqlite3`
- 日志放在 `src_gpt5.5/logs`
- 导出文件放在 `src_gpt5.5/data/exports`

### 2. 配置贴文根目录

贴文 Markdown 默认存放根目录由 `config/app.json` 的 `paths.content_root` 控制。

默认值是：

```json
"content_root": ".."
```

这表示贴文目录在 `src_gpt5.5` 的上一级目录。

如果你迁移到 Linux 或其他目录，可以：

- 直接修改 `config/app.json`
- 或设置环境变量 `TRUTH_CONTENT_ROOT`

### 3. 配置 OpenAI Key

如果要生成中文翻译或启用大模型分析，设置：

```powershell
$env:OPENAI_API_KEY="你的 Key"
```

Linux 下可以在启动前导出环境变量。

### 4. 首次启动

启动脚本会自动做这些事：

- 初始化 SQLite
- 导入/同步用户
- 初始化行情标的
- 启动每日调度器

## 数据与产物

### Markdown

抓取后会保存到 `paths.content_root` 指定的目录下，通常按：

- `年份/月/日期 文件名.md`

组织。

### 附件

附件默认保存到对应贴文目录下的：

```text
attachments/{source_status_id}
```

### SQLite

数据库默认是：

```text
src_gpt5.5/data/app.sqlite3
```

主要表包括：

- `posts`
- `post_attachments`
- `post_terms`
- `post_entities`
- `post_topics`
- `post_china_relevance`
- `post_sentiments`
- `post_market_signals`
- `tasks`
- `task_logs`

## 任务中心

Web 页面里的“任务中心”可手工触发：

- `抓取新增`
- `导入 Markdown`
- `分析贴文`
- `重分析已有贴文`
- `同步行情`
- `回测`
- `预测`

其中：

- `分析贴文`：通常是增量分析，只分析缺失结果的数据
- `重分析已有贴文`：会覆盖已有分析结果，重新计算中国相关性、情绪、主题、实体等
- `导入 Markdown`：从 `paths.content_root` 指定的贴文根目录递归扫描 `.md` 文件入库

### 导入规则

导入 Markdown 时会尽量去重，主要依据：

- `status_id`
- `original_url`
- `source_url`
- `file_path`

如果识别到已有贴文：

- 文件内容未变化，会跳过
- 文件内容有变化，会更新已有记录

如果是更新后的贴文，附件记录也会重新写入。

### 三个容易混淆的入口

- `抓取新增`
  - 从上一次进度继续抓取新的 Truth Social 贴文
  - 适合补抓最新内容
  - 可选自动导入和分析

- `导入 Markdown`
  - 从本地 Markdown 文件重新入库
  - 适合你手工整理、迁移文件后重新扫描
  - 主要解决“文件已经在目录里，但数据库还没收进来”的情况

- `重分析已有贴文`
  - 不重新抓取、不重新导入文件
  - 只对数据库里已有的贴文重新跑分析
  - 适合你修改了中国相关性、主题、情绪等规则后重算结果

## 定时任务

系统内置调度器，仅在服务进程运行时生效。

配置项：

- `scheduler.enabled`
- `scheduler.run_on_startup`

默认会按配置时间执行：

- 每日抓取：`crawler.daily_time`
- 每日行情同步：`market.daily_sync_time`

注意：

- 如果服务没运行，定时任务不会触发
- 如果想无人值守运行，建议配合系统级任务计划或守护进程

## 运维建议

### 查看状态

优先用 `status.ps1` 或 `status.sh`。

它会检查：

- PID 文件
- 端口监听
- 健康检查接口 `/api/settings/health`

### 查看日志

应用日志默认在：

```text
src_gpt5.5/logs/app.log
```

它会按天切分，文件名会带日期后缀，例如：

```text
src_gpt5.5/logs/app.log.2026-06-20
```

如果启动失败，也可以看：

- `server.out.log`
- `server.err.log`

### 进度文件

抓取进度默认保存在：

```text
src_gpt5.5/data/已抓取.md
```

这个文件记录当前已经抓取到的最大编号。删除后会从 0 重新开始。

### 重新分析规则

如果修改了 `config/app.json` 中的中国相关性配置，旧数据不会自动重算。

需要：

- 点击任务中心里的 `重分析已有贴文`

### 常见问题

#### 1. 启动后打不开页面

检查：

- 服务是否真的启动
- 端口是否被占用
- `app.log` / `server.err.log` 是否有错误

#### 2. 中国相关误判太多

调整 `config/app.json` 里的：

- `china_relevance_keywords`
- `china_relevance_excluded_keywords`
- `china_relevance_min_keyword_hits`
- `china_relevance_min_score`

#### 3. 改完配置没有生效

确认：

- 是否重启了服务
- 是否重新运行了“重分析已有贴文”

#### 4. 任务按钮点了 Not Found

通常是旧服务进程还在跑，尚未加载最新代码。请重启服务后再试。

## 安全与提示

- 美股分析、回测和预测仅用于研究，不构成投资建议
- 开放到局域网时，请只在可信网络中使用
- `OPENAI_API_KEY` 不要写进仓库
