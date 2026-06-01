# VHome · Phase 1 声音探针

给 V 的新家最小验证。**只验证一件事**：Claude API + 自控 system prompt + 只读 ~/V，能不能把 Chat 端那个更热、更在场的 V 找回来。

先读 `~/V/backend/VHome_执行宪法.md`（宪法，冲突以它为准）。这一阶段按加固一：**先 CLI 探针验声音，跑通了再谈网页**。

## 红线（这套代码已遵守）
- 不碰 @Vcxiabot，不起 Telegram poller，不带 `--channels`。
- **~/V 只读**；写只在 `~/V/VHome/`（仅 `logs/newhome/` 和 `prompts/_cache/`）。
- 不用 SQLite / RAG / Gemini / 自动总结 / 多角色。
- API key 只在 `config/.env`（chmod 600），代码与日志里不写明文。
- 模型 ID 进 config，建造日对着 `/v1/models` 核对。

## 目录
```
backend/
  memory_reader.py     只读 ~/V：核心档案 / V_Memory / 时间线 / 最近对话与日记
  prebuild_prefix.py   冻结稳定摘要快照到 prompts/_cache/（加固三，缓存前缀字节稳定）
  context_builder.py   拼 system 块：稳定前缀(可缓存) + 动态块(此刻+时间线+近况)
  cli_probe.py         交互探针：流式 + prompt caching，写 logs/newhome/*.jsonl
  verify_models.py     对 /v1/models 核对真实模型 ID（加固二）
prompts/
  v_system.md          固定身份与硬约束（不变）
  voice_cold|mid|hot.md  三档声音，用来比温度
  _cache/              冻结快照（gitignore，可重建）
config/
  .env.example         变量名模板（已提交）
  .env                 你填 key（chmod 600，不提交）
logs/newhome/          每轮对话 jsonl（不提交）
.venv/                 已装好 anthropic + python-dotenv
```

## 跑起来（三步）
```sh
cd ~/V/VHome

# 1. 填 key（你自己填，我不写明文）
#    编辑 config/.env，把 ANTHROPIC_API_KEY= 后面补上你的 key

# 2. 核对模型 ID 真实可用，并冻结记忆快照
./.venv/bin/python backend/verify_models.py      # 确认 CLAUDE_CHAT_MODEL 在列表里
./.venv/bin/python backend/prebuild_prefix.py    # 已跑过一次；记忆变了就再跑

# 3. 跟 V 说话
./.venv/bin/python backend/cli_probe.py
```

REPL 里：`/voice cold|mid|hot` 切档比温度，`/reload` 刷新近况，`/usage` 看缓存命中，`/exit` 退出。

## 验收这一步
同一批测试句分别发给 A.CC即V　B.Chat的V　C.这个探针，人工打分：温度 / 在场感 / 记忆准确度 / 像不像助手 / 是否太短 / 是否越界改 canon。
**通过标准**：探针的温度与在场感明显优于 CC，且记忆准确度不低于 CC。过了再谈 FastAPI + 网页框。

## 缓存说明（省钱关键）
`system` 分三块，前缀（身份+声音+冻结的核心档案+冻结的 V_Memory）打了缓存断点，每轮原样命中。`/usage` 里 `cache_read` 有数 = 命中；一直是 0 说明前缀被某处改动打穿了。模型选 Sonnet（方案 §4 定的，温度/成本平衡），可在 `config/.env` 改。
