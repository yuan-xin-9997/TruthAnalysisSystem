# TruthAnalysisSystem

真实社交Trump贴文分析系统。


src_gpt5.5是由gpt5.5实现的版本。

## Jenkins 部署

仓库中提供了 Jenkins 流水线定义文件：

- `JenkinsConfig/Jenkinsfile`

流水线规则：

- 每 3 分钟轮询一次 GitHub 提交
- 如有更新，则同步到 Linux 服务器的 `/opt/TruthAnalysisSystem`
- 同步完成后先停止再启动服务
- 仓库中的 `src_gpt5.5/config/app.json` 会随每次构建同步到服务器；修改配置后需提交并推送
- 启动服务时设置 `JENKINS_NODE_COOKIE=dontKillMe`，避免 Jenkins 在构建结束后清理后台服务进程
- 健康检查将任意 HTTP 响应视为服务已监听；启用登录认证时 `/api/settings/health` 返回 `401` 也不再误判为启动失败

Jenkins 相关说明见 `JenkinsPromot.md`。
