# 模型配置审核

2026-11-17，Codex 自审。

- `.env` 为 Git ignored，本机使用 `MODEL_PROVIDER=openai`、`MODEL_API_BASE=https://1pkapi.com/v1`、`MODEL_NAME=deepseek-v4.1-flash`。密钥不进入仓库。
- OpenAI 适配覆盖根地址和 `/v1` 地址，调用 `/chat/completions`；Anthropic 适配覆盖根地址和 `/v1` 地址，调用 `/v1/messages`。图片、system、工具调用、SSE 解析有单元测试。
- 模型名缺失或 provider 非 `mock/openai/anthropic` 明确失败；不会静默回退 mock。
- 实测网关列表、非流式文本、非流式图片和流式工具调用均为 200；`deepseek-v4.1-flash` 真实识别图片、DOCX、PDF 成功，TXT 经两次显式重试后也已持久化为 ready（末次约150秒），四份来源 #5–8 均保留于课程 #6；初始失败不抹除。
- 239 后端测试、88 前端测试、构建和安全检查通过；安全依赖扫描最终重试无已知漏洞，npm audit 0，Gitleaks 无发现。
- 真实课程数据和旧配置未删除；Anthropic 仅做协议夹具测试，未宣称真实 Anthropic 账户验收。
