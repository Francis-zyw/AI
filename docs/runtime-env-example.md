# 运行时环境变量说明

本项目新入口（`gb_pipeline_v2`）推荐采用**环境变量驱动**的方式配置模型、Provider 模式、API Key 与 Base URL，避免把密钥写入项目配置文件。

## 目标

把以下信息尽量放到环境中配置：

- Step2 / Step3 / Step4 使用的模型
- Provider 模式
- API Key
- Base URL
- 是否走 Codex 已登录/订阅态

这样不同成员只需切换自己的终端环境，不需要改仓库内配置。

---

## 一、默认行为

默认配置文件：

- `pipeline_v2/runtime_models.ini`
- `pipeline_v2/step3_engine/runtime_config.ini`
- `pipeline_v2/step4_runtime_config.ini`

推荐规则：

1. **优先读取环境变量**
2. 配置文件只保留默认值或占位
3. **不要把 API Key 明文提交进仓库**

---

## 二、推荐环境变量

### 1）按步骤覆盖模型与 Provider

支持以下环境变量：

```bash
export PIPELINE_STEP2_MODEL=gpt-5.4
export PIPELINE_STEP3_MODEL=gpt-5.4
export PIPELINE_STEP4_MODEL=gpt-5.4

export PIPELINE_STEP2_PROVIDER_MODE=env_api_key
export PIPELINE_STEP3_PROVIDER_MODE=env_api_key
export PIPELINE_STEP4_PROVIDER_MODE=env_api_key
```

也支持验证回退模型：

```bash
export PIPELINE_STEP2_VALIDATION_FALLBACK_MODEL=gpt-5.4
export PIPELINE_STEP2_VALIDATION_PROVIDER_MODE=env_api_key
```

### 2）OpenAI / OpenAI 兼容接口

```bash
export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://api.openai.com/v1
```

### 3）OpenRouter

如果下游继续使用 OpenAI 兼容 SDK，可直接映射成：

```bash
export OPENAI_API_KEY=$OPENROUTER_API_KEY
export OPENAI_BASE_URL=https://openrouter.ai/api/v1

export PIPELINE_STEP2_MODEL=openai/gpt-4.1-mini
export PIPELINE_STEP3_MODEL=openai/gpt-4.1-mini
export PIPELINE_STEP4_MODEL=openai/gpt-4.1-mini
```

或者你也可以先单独维护：

```bash
export OPENROUTER_API_KEY=your_openrouter_key
export OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

再由自己的 shell/profile 做映射。

### 4）Gemini

当前项目里部分旧链路支持 `gemini-cli` / Gemini 相关调用，但**新入口 step2/step3 主链当前仍以 OpenAI 兼容调用为主**。

如需 Gemini：

```bash
export GEMINI_API_KEY=your_gemini_key
```

是否可直接用于新入口 step2/step3，取决于对应执行链是否已实现 Gemini 分支。

### 5）Codex 订阅 / 已登录态

配置层预留了：

```bash
export PIPELINE_STEP2_PROVIDER_MODE=codex
export PIPELINE_STEP3_PROVIDER_MODE=codex
export PIPELINE_STEP4_PROVIDER_MODE=codex
```

说明：

- `provider_mode=codex` 代表希望走 Codex 已登录/订阅态
- Step2 / Step3 新入口现在已经会直接调用本机 `codex` CLI
- 运行前请先确认 `codex login status` 返回已登录

结论：

- **配置层：支持声明 codex 模式**
- **执行层：支持直接走 Codex 已登录/订阅态**

---

## 三、终端示例

### 示例 A：官方 OpenAI API

```bash
export PIPELINE_STEP2_PROVIDER_MODE=env_api_key
export PIPELINE_STEP3_PROVIDER_MODE=env_api_key
export PIPELINE_STEP4_PROVIDER_MODE=env_api_key

export PIPELINE_STEP2_MODEL=gpt-5.4
export PIPELINE_STEP3_MODEL=gpt-5.4
export PIPELINE_STEP4_MODEL=gpt-5.4

export OPENAI_API_KEY=your_key
export OPENAI_BASE_URL=https://api.openai.com/v1
```

### 示例 B：OpenRouter

```bash
export PIPELINE_STEP2_PROVIDER_MODE=env_api_key
export PIPELINE_STEP3_PROVIDER_MODE=env_api_key
export PIPELINE_STEP4_PROVIDER_MODE=env_api_key

export PIPELINE_STEP2_MODEL=openai/gpt-4.1-mini
export PIPELINE_STEP3_MODEL=openai/gpt-4.1-mini
export PIPELINE_STEP4_MODEL=openai/gpt-4.1-mini

export OPENAI_API_KEY=$OPENROUTER_API_KEY
export OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

### 示例 C：声明 Codex 模式

```bash
export PIPELINE_STEP2_PROVIDER_MODE=codex
export PIPELINE_STEP3_PROVIDER_MODE=codex
export PIPELINE_STEP4_PROVIDER_MODE=codex

export PIPELINE_STEP2_MODEL=gpt-5.4
export PIPELINE_STEP3_MODEL=gpt-5.4
export PIPELINE_STEP4_MODEL=gpt-5.4
```

说明：Step2 / Step3 会优先走本机 `codex login` 已登录态；只有切回 `env_api_key` 时才需要 `OPENAI_API_KEY`。

---

## 四、建议做法

对于团队协作，建议：

1. 仓库中只保留默认模型与说明
2. 每个人在自己的 shell profile / direnv / launchd 中注入环境变量
3. 不要把 key 写进：
   - `runtime_models.ini`
   - `runtime_config.ini`
   - 命令行参数
4. 如果要提交示例，只提交**无密钥模板**

---

## 五、当前状态说明

截至当前版本：

- 新入口已支持通过环境变量覆盖 step model / provider mode / api key env / base url env
- 新配置说明已改为“优先环境变量，不鼓励明文 key”
- `provider_mode=codex` 已在 Step2 / Step3 新入口配置层与执行层贯通
- 使用 Codex 订阅态前，请先确认 `codex login status` 正常
