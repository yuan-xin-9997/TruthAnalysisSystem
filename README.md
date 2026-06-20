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

Jenkins 相关说明见 `JenkinsPromot.md`。
