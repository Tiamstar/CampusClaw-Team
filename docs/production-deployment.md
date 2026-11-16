# 独立HTTPS部署与本地预演

关联DLV-001。生产覆盖文件为`deploy/compose.production.yml`，需要Docker Compose ≥2.24.4（使用`!reset`移除本地端口映射）。当前完成本机内部CA预演，**没有公网地址或公网受信证书**。服务器、域名、真实外部服务配置和另一成员验收仍需提供。禁止将现有个人教学库、真实附件或本地凭据自动迁移到公网。

## 服务器准备与独立配置

使用专用Linux Docker主机和独立工作目录，确认域名A/AAAA记录均指向该主机，防火墙允许80/443。Caddy需出站访问证书颁发服务；配置真实SMTP/模型/Embedding的出站访问。只发布80/443；不要另行暴露Docker socket、数据库、backend、MCP、Mailpit、上传目录或Caddy数据卷。

```sh
git rev-parse HEAD
python scripts/setup_production.py --host campus.your-domain.example --email ops@your-domain.example
# 在受控编辑器中维护 .env.production，不复制原教学库 .env。
# 配置真实 MODEL_PROVIDER/API、Embedding、SMTP，保留随机数据库和工具凭据。
docker compose --env-file .env.production -p campusclaw-production -f docker-compose.yml -f deploy/compose.production.yml config --quiet
docker compose --env-file .env.production -p campusclaw-production -f docker-compose.yml -f deploy/compose.production.yml build backend frontend campus-tools sandbox-runner
docker compose --env-file .env.production -p campusclaw-production -f docker-compose.yml -f deploy/compose.production.yml --profile build build sandbox-image
```

脚本独占创建`.env.production`，拒绝覆盖，生成全新四组随机凭据，不输出其值。域名只接受DNS主机名，不接受URL、IP、端口、通配符或注入字符。默认仍为mock和内部Mailpit，未配置真实服务时只能当作明确标记的流程演示，不能签真实AI/邮件验收。生产配置/备份需受主机权限和团队保留策略保护。不要把`docker compose config`完整输出或容器inspect环境上传公开仓库。

## 数据初始化与启动

真实使用可启动空库后经注册和教师邀请码创建课程。若部署的是**独立合成验收实例**，须在完整应用首次启动、bootstrap_tools创建平台服务账号之前按 [夹具说明](acceptance-fixtures.md) 导入。生产覆盖中的离线seed命令须额外传入`-e DJANGO_HTTPS_ONLY=0`，仅该进程关闭重定向供进程内初始化；运行中的后端始终启用HTTPS强制跳转。不能在已有真实账号库运行seed，也没有覆盖选项。

```sh
docker compose --env-file .env.production -p campusclaw-production -f docker-compose.yml -f deploy/compose.production.yml up -d --wait --wait-timeout 180
docker compose --env-file .env.production -p campusclaw-production -f docker-compose.yml -f deploy/compose.production.yml ps
```

后端启动会迁移、收集静态资源和初始化平台工具。首次数据库无需恢复旧数据；升级已有部署时必须先备份、在独立环境验证迁移/恢复。不要使用`down -v`，不要复用现有`campusclaw-team`卷。Caddy证书数据保留于该项目独立caddydata卷。不要同时在同一宿主用不同项目标签重建相同镜像；运行容器不会自动换镜像，但后续重建应使用经记录的提交及镜像ID。

生产数据库/媒体完整备份与隔离恢复须明确来源项目，不使用默认本地来源：

```sh
python scripts/rehearse_recovery.py --backup-dir ../.backups/production-new-run --project campusclaw-production --env-file .env.production --compose-file docker-compose.yml --compose-file deploy/compose.production.yml
```

具体来源核对、私有目录、保留和RPO/RTO限制见 [恢复说明](recovery-rehearsal.md)。该命令备份数据库/媒体，不备份Caddy私钥或生产环境密钥，后两者需另按受控配置恢复流程保管；不可把业务数据一致性恢复当作完整公网站点恢复。

## TLS代理与权限

Caddy终止TLS，业务路径直接转发后端，前端Nginx仅服务SPA。边缘代理覆盖`X-Real-IP`/`X-Forwarded-Proto`，API和SSE不经过二次Nginx代理。后端端口不发布，生产覆盖启用可信TLS头、HTTPS跳转、安全Cookie、一天HSTS；不设置includeSubDomains/preload。后台CSRF按HTTPS同源判定。私有HTTP健康检查豁免跳转，数据库故障仍503，不能把跳转成功当作健康。

信任头仅限此拓扑；若加CDN/第二代理，必须重新配置可信代理和限流来源，不得直接透传用户头。固定到源站的Host须通过ALLOWED_HOSTS，Caddy只服务配置域名。MCP和执行代理仍是内部服务；Docker socket持有者具主机高权限，隔离执行应使用专用主机，不能与敏感系统混放。

## 可重复内部CA预演

先构建上述镜像并拉取`caddy:2.10.2-alpine`。无需公网或服务器，脚本创建独立配置/网络/数据库/附件卷，无宿主端口，禁止联网；只使用合成数据、mock和内部Mailpit。路径必须是仓库外的新私有目录，项目名必须以`https-rehearsal-`开头，不能复用已有项目或数据卷。

```sh
python scripts/rehearse_https.py --output-dir ../.https-new-run --project https-rehearsal-new-run
```

脚本先迁移/导入，再正常启动全部服务。导出本地CA根证书，客户端显式信任该证书并校验证书主机名，**不使用跳过TLS验证**。实测健康/SPA、三身份密码登录、成绩与跨班权限、安全Cookie、后台CSRF正反例、协议/IP伪造、HTTP跳转及mock SSE完成。结束停止并保留所有资源、业务数据及失败日志，不执行清库/删卷；再次验证要选择新项目。限流测试会留下429记录，可能影响同一源IP随后一分钟内的登录，属于预演的保留证据。

本地预演不证明DNS/ACME公网签发、服务器防火墙、真实模型、真实邮件、容量或非主实现者验收。实际结果及局限见 [审核记录](../reports/https-deployment.md)。

## 公网交付出口

域名与证书准备好后，由另一成员在同一提交验证：受信任公网HTTPS及HTTP跳转；学生/教师三条底座主路径和E1/E3/E4/E5；流式聊天和公式窄屏；真实SMTP/模型/引用；越权/失败恢复；备份恢复与冻结的容量/RPO/RTO。记录公网URL、提交、镜像、时间、执行者和脱敏证据，不能仅以静态首页或本机CA预演宣称交付。新数据库用户和真实账号数据保留政策须由团队决定，不能把本机数据直接公开。
