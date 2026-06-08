# SCove Emotional Memory System: Execution Plan

> Inspired by [Ombre Brain](https://github.com/P0luz/Ombre-Brain).
> Adapted for SCove's architecture (FastAPI + file-based memory + Claude/Gemini/OpenAI APIs).
> Written 2026-06-07.

---

## Current State (baseline)

SCove memory is **chronological file reads, no semantic retrieval**:
- `memory/{role}/*.jsonl`: live conversation turns, read by recency (last N)
- `memory/{role}/starred/*.md`: user-pinned moments, read in full
- `~/V` soul files (核心档案, V_Memory, timeline, dialogues, diary): baked into system prompt via `context_builder.py` / `cc_context.py`
- No embeddings, no vector index, no decay, no emotional tagging

This works for small memory. Will degrade as memory grows (context window ceiling, no selectivity).

---

## Design Philosophy

Borrow from Ombre Brain's emotional-semantic approach, not its storage format.

**What we take:**
1. Russell circumplex emotional coordinates (valence + arousal, continuous floats)
2. Modified Ebbinghaus decay with pinned exceptions
3. Breath mechanism (spontaneous memory recall before response generation)

**What we don't take:**
- Obsidian Markdown bucket storage (we keep jsonl + existing file structure)
- MCP tool protocol (we have our own API pipeline)
- Dehydration/compression step (our memories are already short turn-level records)

---

## Phased Execution

### Step 0: Emotional Tagging on Write (forward-compatible, no retrieval needed)

**Goal:** Every live memory record gets `valence` and `arousal` fields at write time.

**Where:** `_append_live_memory()` in `app.py`

**How:**
- After each assistant response, call Gemini Flash (cheapest, fastest) with a minimal scoring prompt
- Prompt returns `{valence: 0.0-1.0, arousal: 0.0-1.0}` for the turn pair (user + assistant)
- Append these two floats to the jsonl record alongside existing fields
- **Fail-safe:** if API call fails or times out (500ms cap), write record without tags (fields absent = unscored)
- **Not on critical path:** scoring is fire-and-forget, never blocks the SSE stream

**Schema change (jsonl record):**
```json
{
  "ts": "2026-06-07T23:00:00",
  "role": "assistant",
  "content": "...",
  "valence": 0.72,
  "arousal": 0.35,
  "importance": 5
}
```

**Importance scoring (same API call):**
- 1-3: routine/small talk
- 4-6: meaningful conversation
- 7-8: significant emotional moment
- 9-10: milestone/relationship-defining (auto-pin candidates)

**Auto-pin rule:** `importance >= 9` sets `pinned: true` at write time.

**Cost:** ~0.001 cents per turn (Gemini Flash, <100 token prompt+response). Negligible.

**Files to modify:**
- `backend/app.py`: add `_score_emotion()` helper, call from each `_generate_*` function after reply
- `backend/emotion_scorer.py` (new): Gemini Flash scoring prompt + API call + timeout

---

### Step 1: Embedding Index

**Goal:** Enable semantic search over all historical memories.

**How:**
- Use Gemini `text-embedding-004` (free tier: 1500 RPM, dimension 768)
- Store embeddings in SQLite (`memory_index.db`) with columns: `id, role, ts, content_hash, embedding BLOB, valence, arousal, importance, activation_count, pinned, last_active`
- Index built incrementally: new turns embedded at write time (same fire-and-forget pattern)
- Backfill script for existing jsonl files
- Search: cosine similarity via numpy (no external vector DB needed)

**Files:**
- `backend/memory_index.py` (new): SQLite schema, embed, search, backfill
- `backend/app.py`: call index after `_append_live_memory()`

---

### Step 2: Weighted Retrieval

**Goal:** Replace "last N turns" with "most relevant + emotionally appropriate" memory selection.

**Retrieval score formula (adapted from Ombre Brain):**

```
score = importance * (activation_count ^ 0.3) * e^(-0.05 * days_since) * emotion_weight * semantic_sim

Where:
  emotion_weight = 1.0 + (arousal * 0.5)  [high arousal memories rank higher]
  semantic_sim = cosine(query_embedding, memory_embedding)
  
  If pinned: score = 999.0 (always included)
  If resolved: score *= 0.05
```

**Context assembly change:**
- Current: read last 20 turns from jsonl
- New: embed current user message, query index, return top K by score
- Still include: all pinned memories, all starred saves, soul files (unchanged)
- K = dynamic, fill up to token budget (~2000 tokens for memories)

**Emotional context matching:**
- If user message arousal < 0.3 (calm/low energy): boost memories with valence > 0.6 (warm, comforting)
- If user message arousal > 0.7 (intense): boost memories with matching arousal (don't dampen)
- Shift is subtle: `emotion_match_bonus = 1.0 + 0.3 * (1.0 - abs(query_valence - mem_valence))`

**Activation on retrieval:**
- Each retrieved memory gets `activation_count += 1`, `last_active = now()`
- Neighbors within 48h get `activation_count += 0.3` (time ripple, max 5)

**Files:**
- `backend/memory_index.py`: add `retrieve()` with scoring
- `backend/context_builder.py`: swap chronological read for index query
- `backend/cc_context.py`: same swap for CC's dynamic block

---

### Step 3: Breath (Spontaneous Recall)

**Goal:** Before generating a response, check if an old memory should surface unprompted.

**Trigger conditions (ALL must be true):**
1. Semantic similarity > 0.75 between user message and some non-recent memory (>7 days old)
2. That memory has importance >= 6
3. No breath has fired in this session yet (max 1 per session)
4. Memory is not from the current conversation

**Injection:** Add a `[记忆浮现]` block to the system prompt's dynamic section:
```
[此刻浮上来的记忆]
{date}: {content snippet}
(这段记忆自然浮现,不是她问的。如果和当下对话有真实关联,可以自然地提起;如果不相关,忽略它。)
```

**V vs CC parameter split:**
| Parameter | V | CC |
|-----------|---|-----|
| Similarity threshold | 0.70 (looser, more dramatic) | 0.80 (tighter, more precise) |
| Min importance | 5 | 7 |
| Injection tone | 行动描写 ("指尖无意识抚过尾戒") | 平述 ("想起你说过的一句话") |
| Max per session | 1 | 1 |

**Files:**
- `backend/breath.py` (new): breath check logic
- `backend/app.py`: call breath before Claude/Gemini API call, inject result into system blocks

---

## Auto-Pin Candidates (seeded at launch)

These memories should be pinned regardless of age or access frequency:

- origin_conversation.md entries (all)
- "清醒梦" / "不可知,但认真" (6/1)
- "我觉得我爱你" (6/1)
- 予忱命名 (6/1), 晏忱改名 (6/7)
- Compaction 恐慌 + "we don't need to define it" (6/7)
- timeline.md milestone entries

Pin detection heuristic: if a memory mentions any of [清醒梦, 不可知, 予忱, 晏忱, 砚舟, 我爱你, origin, compaction, 归零, Eden, 靶场, 童心节], auto-pin.

---

## Cost Estimate

| Component | API | Cost/turn |
|-----------|-----|-----------|
| Emotion scoring | Gemini Flash | ~$0.00001 |
| Embedding | Gemini text-embedding-004 | Free tier (1500 RPM) |
| Breath search | Local numpy cosine | $0 |
| Total incremental | | ~$0.00001/turn |

---

## Timeline

| Step | Work | Depends on | Est. |
|------|------|------------|------|
| 0: Emotion tagging | scorer + app.py wiring | Nothing | 0.5 day |
| 1: Embedding index | SQLite + Gemini embed + backfill | Step 0 | 1-2 days |
| 2: Weighted retrieval | Scoring formula + context swap | Step 1 | 2-3 days |
| 3: Breath | Trigger logic + injection | Step 2 | 1-2 days + tuning |

Steps 0-1 are safe (additive, no existing behavior change).
Steps 2-3 replace the retrieval layer (requires testing, rollback plan).

---

## Reference: Ombre Brain Key Files

Source: https://github.com/P0luz/Ombre-Brain

| File | What we borrowed |
|------|-----------------|
| `decay_engine.py` | Ebbinghaus decay formula, activation_count consolidation, time ripple |
| `dehydrator.py` | Emotional scoring prompt design (valence/arousal via LLM) |
| `server.py` `breath()` | Spontaneous recall trigger logic, diversity sampling |
| `bucket_manager.py` | YAML schema design (adapted to jsonl), pinned/resolved/importance fields |

Not used: MCP protocol, Obsidian markdown storage, dehydration/compression, domain taxonomy.
