# ruyi-telegram-bot

[English](README.md) | **简体中文**

这是从 [`ruyisdk-test/riko-bot`](https://github.com/ruyisdk-test/riko-bot)
拆分出来的独立 Telegram 通知与人工交互传输服务。

本服务接收通用 HTTP/JSON 消息请求，渲染 Telegram 消息和按钮，接收人工选择，
将结果事件路由到配置的工作流，并向 Telegram 用户反馈 callback 投递状态。
它不会解释选项的业务含义。

## 架构

原 Riko 的职责被拆分为三个服务：

```text
original riko-bot
   |
   +-- test-bot          测试 / 检测 / 查询
   +-- package/PR bot    打包 / 变更 / Pull Request
   +-- telegram-bot      通知 / 人工交互 / 结果路由
```

AI 是可以参与任一工作流的横向能力，不是固定的中央上游、callback 消费者或路由器。

```text
workflow/service
    | Human Interaction Request
    v
ruyi-telegram-bot -> Telegram -> human selection
    |
    | Human Interaction Result
    v
configured consuming workflow
```

请求生产者、选项生产者、人工决策者和结果消费者可以彼此不同。因此，
`callback_target` 标识结果消费者，而不是请求者，也不会默认指向请求者。

服务之间通过 HTTP/JSON 通信。本仓库不会从其他仓库导入 test、package、
Manifest、nvchecker 或 PR 业务代码。

## 职责与边界

本服务提供：

- `GET /health` 和 `GET /version`；
- 用于纯文本和可选按钮的 `POST /api/v1/messages`；
- 默认或请求级 Telegram chat ID；
- HTTP(S) URL 按钮；
- 动态的 0 到 N 个 action 选项，每行最多渲染两个；
- Telegram callback 长轮询和即时 callback acknowledgement；
- 通过受控配置进行逻辑 callback target 路由；
- 旧版单消费者 callback 转发；
- received、delivered 和 failed 传输反馈。

本服务不提供 package/test/PR 决策、AI 推理、模型客户端、工作流任务状态、
选项语义、上下文恢复、数据库、Redis、消息队列、持久化重试、调度器、API 认证，
也不提供自由文本 Telegram 状态机。

消费工作流负责保存所有 package、failure、patch、PR、prompt、reasoning 和任务上下文，
并使用 `interaction_id` 恢复这些上下文。

## 环境要求与安装

- Python 3.10 或更高版本（推荐 Python 3.12）
- Poetry
- FastAPI、httpx、Pydantic 和 `python-telegram-bot`

```bash
poetry install
cp .env.example .env
```

不要提交真实 Telegram token、chat ID、代理凭据或包含凭据的 callback endpoint。

## 配置

```env
APP_HOST=127.0.0.1
APP_PORT=9878

TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=

CALLBACK_TARGETS_JSON={"test-workflow":"http://127.0.0.1:9877/callback","package-pr-workflow":"http://127.0.0.1:9880/callback"}
CALLBACK_FORWARD_URL=

HTTP_PROXY=
HTTPS_PROXY=
```

服务启动时必须配置 `TELEGRAM_TOKEN`。如果每个消息请求都提供 `chat_id`，
则 `TELEGRAM_CHAT_ID` 可以为空。

`CALLBACK_TARGETS_JSON` 是可选的 JSON 对象，用于把逻辑 target 名映射到受控的
HTTP(S) endpoint。服务启动时会解析它；无效 JSON、空白 target 名、非字符串值和
非 HTTP(S) endpoint 会立即导致启动失败。调用方只提交逻辑 `callback_target`，
不能提交任意 callback URL。添加 target 只需修改配置，不需要修改 callback 路由代码。

`CALLBACK_FORWARD_URL` 是旧版/默认的单消费者路由：

- 带显式 target 的新 interaction 只使用 registry；
- 未知的显式 target 会报错，绝不会回退；
- 不带 target 的新 interaction 使用 `CALLBACK_FORWARD_URL`；
- 旧版 `action` 使用 `CALLBACK_FORWARD_URL`；
- 如果 action button 请求没有任何可用路由，则在发送 Telegram 消息之前返回 HTTP 422。

Telegram HTTPS 流量优先使用 `HTTPS_PROXY`，并以 `HTTP_PROXY` 作为 fallback。
其他既有环境代理行为保持不变。

服务默认监听 `127.0.0.1:9878`。只有部署确有需要时才绑定其他地址。

## 运行

```bash
poetry run python -m telegram_bot
```

或者：

```bash
poetry run python -m uvicorn telegram_bot.main:app --host 127.0.0.1 --port 9878
```

## 健康检查与版本

```bash
curl http://127.0.0.1:9878/health
curl http://127.0.0.1:9878/version
```

```json
{"status":"ok"}
```

```json
{"version":"0.1.0"}
```

## Web Console

正常启动服务：

```bash
poetry run python -m telegram_bot
```

然后打开 [http://127.0.0.1:9878/console](http://127.0.0.1:9878/console)。
Console 面向本地或内部开发、联调和演示，提供五个桌面页面：

- **Overview**：汇总配置和运行状态；
- **Send Message**：构造纯文本通知和 URL 按钮；
- **Interaction**：构造决策请求，并预览无状态 callback data 的字节预算；
- **Routing**：以只读方式显示经过安全脱敏的 callback targets；
- **About**：说明服务 API 和架构边界。

两个消息构造器都调用既有的 `POST /api/v1/messages` endpoint；Console 不会复制
Telegram 投递或 callback 路由逻辑。运行时配置为只读，不暴露 secret，也不会存储
持久化 interaction 历史。状态数据由 `GET /api/v1/console/status` 提供；它只报告配置
布尔值，不返回 token、chat ID 或代理地址。Routing 页面只显示 callback endpoint 的
scheme、hostname 和非默认端口，不会把 userinfo、path、query 或 fragment 发送给浏览器。

## 消息 API

### 纯文本

```json
{
  "text": "Telegram service smoke test"
}
```

请求级 `chat_id` 会覆盖 `TELEGRAM_CHAT_ID`：

```json
{
  "text": "Send to another chat",
  "chat_id": 123456789
}
```

成功响应：

```json
{
  "success": true,
  "chat_id": 123456789,
  "message_id": 456
}
```

Telegram 发送失败时返回 HTTP 503，并使用经过清理的错误信息。

### URL 按钮

只有 URL 按钮的消息不需要 interaction 字段：

```json
{
  "text": "PR created",
  "buttons": [
    {
      "type": "url",
      "text": "View PR",
      "url": "https://github.com/qingwan12138/ruyi-telegram-bot"
    }
  ]
}
```

URL 按钮只接受 `http://` 和 `https://`，并拒绝 `option_id` 和旧版 `action` 字段。

### 人工交互

新的 action 选项需要 `interaction_id`，并使用 `option_id`。选项数量是动态的；
“Manual review” 只是普通选项，没有特殊逻辑。同一 interaction 内每个 `option_id`
必须唯一，但不要求全局唯一，也可以在另一个 `MessageRequest` 中复用。

```json
{
  "text": "Choose an action",
  "interaction_id": "decision-789",
  "callback_target": "package-pr-workflow",
  "buttons": [
    {
      "type": "action",
      "text": "Retry",
      "option_id": "retry"
    },
    {
      "type": "action",
      "text": "Manual review",
      "option_id": "manual"
    }
  ]
}
```

投递给已配置消费工作流的结果示例：

```json
{
  "event": "telegram.interaction.selected",
  "interaction_id": "decision-789",
  "option_id": "manual",
  "option_text": "Manual review",
  "chat_id": 123456789,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

`interaction_id + option_id` 是稳定的机器协议。`option_text` 是可选的 best-effort
展示元数据，从 Telegram 消息的 inline keyboard 中恢复，可能为 `null`。
消费者不能把自然语言 `option_text` 当作机器 action key。Telegram 服务不会保存完整的
AI、test、package 或 PR 上下文，也不会尝试理解 `manual` 或其他选项的含义。
消费工作流使用 `interaction_id` 保存并恢复这些业务上下文。

## Callback data 协议

新按钮使用无状态的短编码：

```text
h1|<target-character-count>|<interaction-character-count>|<target><interaction><option>
```

长度前缀使用 Unicode 字符数。完整编码值（包括前缀和长度）另行限制为最多 64 个
UTF-8 字节。使用 `CALLBACK_FORWARD_URL` 的新 interaction 将 target 长度编码为 0。
64-byte 限制只适用于 Telegram `callback_data`，不适用于 callback HTTP JSON body；
`option_text` 永远不会加入 `callback_data`。

decoder 会安全拒绝非法前缀、非法长度、越界、空 interaction/option ID，以及超过字节限制
的 payload。`h1|` 是保留前缀，旧版 action 不能以它开头。服务不使用内存 callback map，
因此重启不会丢失路由上下文。

## Callback 反馈

服务使用 long polling，不需要公开的 Telegram webhook。

1. 收到 Telegram 点击后，`answerCallbackQuery` 显示 `Selection received.`
2. 目标 HTTP endpoint 接受结果后，向用户显示 `Selection delivered successfully.`
3. 对新的 `InteractionResult`，目标返回 HTTP 409 时显示
   `This interaction has already been resolved.`
4. 未知 target、畸形数据或任何其他非 2xx HTTP response 显示
   `Failed to deliver your selection.`
5. timeout、连接错误、连接重置或其他网络不确定性显示
   `Could not confirm delivery of your selection.`

因此，`DeliveryOutcome` 的投递结果语义是：2xx = `DELIVERED`；只有新
`InteractionResult` 的 409 = `ALREADY_RESOLVED`；其他所有非 2xx HTTP response 和
路由解析失败 = `FAILED`；timeout 或网络不确定性 = `UNKNOWN`。对于旧版
`telegram.action`，HTTP 409 属于 `FAILED`，因为事件没有
`interaction_id`。301、302、307 和 308 等 redirect response 不会被跟随，结果为 failed。
Unknown 不表示目标一定没有收到请求：请求可能已经完成，只是响应丢失。

“Received” 表示 Telegram 已把点击交给本服务。“Delivered” 表示目标工作流接受了 HTTP
结果。这两种反馈都不表示业务工作流、AI、test、package update 或 PR 已成功完成。
真正的业务处理完成后，工作流可以再次调用 `POST /api/v1/messages` 发送结果消息。

acknowledgement、转发和反馈发送失败彼此隔离，不会终止 polling loop。本服务不会自动重试
unknown 投递，因为自动重试可能重复业务副作用。项目有意不提供持久化重试队列。

### 消费者幂等契约

消费工作流必须使用 `interaction_id` 作为幂等键实现业务级幂等。一个 interaction 原则上
只接受一次最终人工决策：第一个有效选择把 interaction 从 pending 转为 resolved，之后同一
interaction 的选择返回 HTTP 409。`callback_query_id` 是传输元数据，不是业务幂等键。

Telegram Bot 不保存 resolved interaction，也不执行业务去重。它没有数据库、Redis/Valkey
状态、内存 resolved map 或业务状态机；这些职责属于消费工作流。

## 旧版 action 兼容性

配置 `CALLBACK_FORWARD_URL` 后，既有调用方可以继续使用不透明的 `action` 按钮：

```json
{
  "text": "Legacy decision",
  "buttons": [
    {
      "type": "action",
      "text": "Continue",
      "action": "task123:continue"
    }
  ]
}
```

投递事件保持不变：

```json
{
  "event": "telegram.action",
  "action": "task123:continue",
  "chat_id": 123456789,
  "message_id": 456,
  "user_id": 789,
  "username": "example",
  "callback_query_id": "xxxx"
}
```

旧版 action 按钮和新 action 按钮不能混合在同一请求中。有意保留的 contract 变化是：
没有 `CALLBACK_FORWARD_URL` 时，旧版 action 会被拒绝，而不是创建只能记录选择的按钮。

## 校验与安全

- request 和 model 对象拒绝未知字段；
- message 和 identifier 字符串会被 trim，且不能为空；
- interaction 字段只在使用新 action 选项时接受；
- callback target 是否存在，由 route/service 层结合运行时 registry 校验，不放入纯
  Pydantic model；
- callback endpoint URL、query token、Telegram token、代理凭据和异常详情不会输出到
  日志或用户反馈；
- 畸形 callback 和投递失败不会终止 polling。

## 测试

```bash
poetry run pytest -q
python -m compileall telegram_bot tests
```

单元测试使用 fake 和 `httpx.MockTransport`，不需要真实 Telegram 账号。只有本地存在可用的
`TELEGRAM_TOKEN` 和 `TELEGRAM_CHAT_ID` 时，才运行真实 smoke test。

## 与原 Telegram 实现的关系

本项目保留了原 Riko 实现中经过验证的环境 token/chat 配置、支持代理的
`python-telegram-bot` 客户端、FastAPI message endpoint、URL 按钮、inline keyboard
布局、long polling、安全错误日志和 Telegram 503 行为。

本项目不会重新引入 `PackageReportData`、`PackageReportService`、package enrichment、
Manifest/PR 字段、scheduler 行为或持久化。
