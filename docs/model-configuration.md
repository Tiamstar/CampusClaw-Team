# 模型协议与本地配置

实际密钥仅放本地 `.env` 或部署环境变量；`.env` 已被 Git 忽略，示例文件不含真实凭据。修改 `.env` 后必须重建使用环境配置的容器，仅重启进程不会加载新值。不要把 `docker compose config` 的完整输出贴到日志，其中包含密钥。

`MODEL_PROVIDER` 表示协议，只接受 `mock`、`openai`、`anthropic`。厂商名称不作为协议值。真实协议必须设置精确的 `MODEL_NAME`，拼错协议或缺失模型直接失败，不会伪装演示成功。

## OpenAI 兼容接口

```dotenv
MODEL_PROVIDER=openai
MODEL_API_BASE=https://your-gateway.example/v1
MODEL_NAME=your-model-id
MODEL_API_KEY=replace-locally
```

支持根地址或以 `/v1` 结尾的地址，内部请求 `/v1/chat/completions`；不要填写整个 completions 路径。使用 Bearer 认证、OpenAI messages、多模态 image_url、function tools 和 SSE。模型须支持对应能力；兼容接口不保证每个模型都支持视觉或工具。

## Anthropic 兼容接口

```dotenv
MODEL_PROVIDER=anthropic
MODEL_API_BASE=https://api.anthropic.com
MODEL_NAME=your-model-id
ANTHROPIC_API_KEY=replace-locally
```

Base 留空使用官方根地址；也支持以 `/v1` 结尾的地址，避免重复版本路径。请求 `/v1/messages`，使用 `x-api-key` 和 `anthropic-version`；优先读取 `ANTHROPIC_API_KEY`，为空时退回 `MODEL_API_KEY`。切换服务商时应清空旧专用密钥，避免优先级选中旧值。适配器转换 system、base64 图片、tool_use/tool_result，按 Anthropic SSE 事件消费。当前输出上限 2048 token，长文可能截断并明确失败；未在此轮宣称真实 Anthropic 平台已验证。

模型路由是应用级配置，HTTP 和后台任务统一使用；本轮没有增加按任务/课程分开存储凭据的配置中心。Embedding 使用独立的 `EMBEDDING_*` 配置，切换聊天模型不等于重新生成索引或支持另一种 Embedding 协议。

## 本机当前选择

2026-11-17 用户明确选择 `deepseek-v4.1-flash`：本机 `.env` 配置 `MODEL_PROVIDER=openai`、`MODEL_API_BASE=https://1pkapi.com/v1`、`MODEL_NAME=deepseek-v4.1-flash`，凭据在忽略文件内，不复制到本文或提交。先前 `deepseek-v4-pro` 的探测不作为 flash 的准确率证据。

应用新配置使用 `docker compose up -d --no-deps backend exam-worker forum-worker index-worker coursework-worker skill-monitor`。这不会删除课程、上传文件或成绩。未来更换协议按上述字段修改，再重建对应容器。运行与验证结果见 [审核记录](../reports/review-model-configuration.md)。
