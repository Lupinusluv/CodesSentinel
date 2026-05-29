# Handoff — v0.5.2 代码质量修复（P1）

> 来源：2026-05-30 全项目审计（"架构和测试"会话）。本文交给"编写代码"会话实现。
> 性质：**非紧急、非阻断**。三条都是真实代码缺陷，但当前 demo 路径（Python 仓库、本地 Redis、现版 langgraph）都不触发崩溃，属健壮性/质量打磨。可在任意空档插入。
> 已在本次审计同步修掉的 P0（文档虚报）见 git 工作区改动，不在本文范围。

实现前先确认职责为"编写代码"，按 CLAUDE.md：只 push feature 分支，提交前找"架构和测试"会话过一遍。

---

## 总览

| 编号 | 模块 | 问题一句话 | 触发条件 | 优先级 |
|---|---|---|---|---|
| P1-1 | `rag/chunker.py` | JS/TS 分块符号名大面积丢失 + 嵌套箭头函数被当独立 chunk | 索引 JS/TS 仓库时 | 中 |
| P1-2 | `core/dependencies.py` | `get_arq_pool` 手写解析 Redis URL，不支持鉴权/`rediss://`/db 索引 | 换带密码或 TLS 的 Redis | 中 |
| P1-4 | `tasks/review_task.py` | 用硬编码字符串 `name == "LangGraph"` 判断图终态 | langgraph 升级改了 root run 名 | 低（隐性版本耦合） |

> P1-3（pgvector 无 ANN 索引，`<=>` 走全表顺扫）经评估**不在本批**：demo 规模 ≤200 文件、≤约 200 chunk，顺扫完全够用，加 ivfflat/hnsw 反而带来"低基数下召回下降 + 需调参"的副作用。建议仅在文档里标成"已知规模权衡"，不动代码。若未来真要做，见文末附录。

---

## P1-1　chunker.py：JS/TS 符号名丢失 + 嵌套箭头过度分块

### 现象
`rag/chunker.py:84 _get_name()` 只认 `child.type == "identifier"`：

```python
def _get_name(node: Node) -> str | None:
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode() if child.text else None
    return None
```

- **Python**：`function_definition` / `class_definition` 的名字节点就是 `identifier` → 正常。
- **JS/TS** 出问题：
  - `method_definition` 的名字是 **`property_identifier`**，不是 `identifier` → 返回 `None`。
  - `arrow_function` 本身**匿名**，没有名字子节点；名字在父级 `variable_declarator` 上（`const foo = () => …` 里的 `foo`）→ 返回 `None`。
- 且 `arrow_function` 在 `_SPLIT_TYPES` 里，`_walk` 递归全树，**任意位置**的箭头函数（含 `arr.map(x => …)` 这种内联回调）都会被切成一个独立 chunk，symbol_name 全空。注释写的"仅顶层"与实际不符。

后果：索引 JS/TS 仓库时，`code_chunks.symbol_name` 大面积为空，且混入大量无意义的内联箭头 chunk，污染 RAG 召回质量。Python 仓库不受影响（demo 仓库是 Python，所以一直没暴露）。

### 建议改法
两步，**实现前先在容器内用 tree-sitter-javascript 0.23.1 实际打印一遍 AST 节点类型核实字段名**（grammar 版本不同字段名可能有差异，别凭本文断言）：

1. **`_get_name` 兼容 `property_identifier`**（修 method）：
   ```python
   _NAME_TYPES = {"identifier", "property_identifier"}
   def _get_name(node: Node) -> str | None:
       for child in node.children:
           if child.type in _NAME_TYPES:
               return child.text.decode() if child.text else None
       return None
   ```

2. **箭头函数：只切"具名顶层"，名字从父级取**。两个选择，倾向 (b)：
   - (a) 给 `_walk` 传 parent，遇 `arrow_function` 时向上找 `variable_declarator` 的 name；或
   - (b) **把 `arrow_function` 从 `_SPLIT_TYPES` 移除**，改为：当遇到 `variable_declarator`（或 `lexical_declaration`）且其初始化值是 `arrow_function` 时，以 declarator 的 identifier 为名、以箭头函数体范围为 chunk。这样内联回调箭头自然不再单独成块，且具名箭头拿到名字。

   (b) 更干净，能同时解决"匿名内联噪声"和"具名箭头丢名字"。

### 测试
`backend/tests/` 下加 chunker 单测（纯函数、无 IO，最容易测）：
- `const foo = (x) => x+1` → 一个 chunk，`symbol_name=="foo"`。
- `class A { bar() {} }` → method chunk `symbol_name=="bar"`。
- `items.map(x => x*2)` 这种内联箭头 → **不**单独产 chunk（或至少不产 symbol_name 为空的噪声块）。
- Python 行为**不回归**：现有 def/class 分块结果不变。

### 风险
低。纯索引侧逻辑，改完重跑一次 demo 仓库索引验证 `code_chunks` 数量与 symbol_name 合理即可。不影响已存的 Python chunk。

---

## P1-2　dependencies.py：Redis URL 解析脆弱

### 现象
`core/dependencies.py:68 get_arq_pool()`：

```python
url = settings.redis_url          # redis://localhost:6379/0
parts = url.replace("redis://", "").split("/")[0].split(":")
host = parts[0]
port = int(parts[1]) if len(parts) > 1 else 6379
_arq_pool = await create_pool(ArqRedisSettings(host=host, port=port))
```

只取了 host/port，**丢掉了 db 索引（`/0`）、密码、`rediss://` TLS**。带鉴权的 URL（`redis://:pwd@host:6379/1`）会把 `:pwd@host` 整段当 host 解析直接连不上；用 ACL/TLS 的托管 Redis 同样挂。当前 prod 是裸 `redis://redis:6379/0` 才一直没事。

> 注意：`get_redis()`（同文件 :56）用的是 `aioredis.from_url(settings.redis_url)`，**已经**正确解析整串。只有 arq 这条是手写解析——两条路径对同一个 URL 解释不一致，是隐患本身。

### 建议改法
用 arq 自带的 DSN 解析，删掉手写拆分：

```python
from arq.connections import RedisSettings as ArqRedisSettings
...
_arq_pool = await create_pool(ArqRedisSettings.from_dsn(settings.redis_url))
```

**实现前核实**：arq 0.26.1 的 `RedisSettings.from_dsn` 是否存在及签名（`from_dsn(dsn: str)`）。本地未装 arq 没跑通验证；进容器 `python -c "from arq.connections import RedisSettings; print(RedisSettings.from_dsn)"` 确认后再改。若该版本无 `from_dsn`，退而用标准库 `urllib.parse.urlparse` 完整解析 host/port/password/db。

### 测试
- 集成测试若已连本地 Redis，改完不回归（`redis://localhost:6379/0` 仍通）。
- 加单测：传 `redis://:secret@example.com:6380/2`，断言解析出的 host/port/db/password 正确（用 from_dsn 返回的 RedisSettings 字段断言，不真连）。

### 风险
中。这是连接初始化路径，改完必须在 prod compose 环境实跑一次（入队一个 review，确认 worker 能消费）——参见 [[project-deploy-notes]] 改码必须 `--build`。

---

## P1-4　review_task.py：硬编码 `"LangGraph"` 判断图终态

### 现象
`tasks/review_task.py:97`：

```python
elif kind == "on_chain_end" and name == "LangGraph":
    final_state = event["data"].get("output")
```

靠 langgraph 内部 root run 的名字字符串 `"LangGraph"` 来抓最终状态。一旦升级 langgraph 改了这个内部命名，`final_state` 永远是 `None` → 下一行 `raise RuntimeError("LangGraph returned no final state")` → **每个审查都失败**。当前 0.2.53 能跑，但这是个看不见的版本地雷。

### 建议改法
改用"事件是否为根"判断，不依赖名字。astream_events v2 每个事件带 `parent_ids`，**根图事件的 `parent_ids` 为空**：

```python
elif kind == "on_chain_end" and not event.get("parent_ids"):
    final_state = event["data"].get("output")
```

**实现前核实**：在容器内打印一次 `astream_events(..., version="v2")` 的事件，确认 (a) 根 `on_chain_end` 的 `parent_ids` 确为空 `[]`，(b) `data.output` 仍是完整 ReviewState。若 `parent_ids` 字段在该版本不可靠，备选：捕获第一个 `on_chain_start`（同样 parent_ids 为空）的 `run_id`，再用 `run_id` 匹配对应的 `on_chain_end`——比字符串名稳。

> 顺带（可选）：把魔法字符串收敛成模块常量，或加注释说明为何这样判根，便于下次升级排查。

### 测试
- 现有 review 集成测试不回归（仍能拿到 final_state、写出 issues）。
- 跑一次 paste 模式端到端，确认 `done` 事件正常、issues 落库。

### 风险
低。改完跑一遍 review 即可验证；逻辑等价替换。

---

## 实现顺序建议
1. **P1-1**（纯函数、好测、零外部依赖）先做，建 chunker 单测。
2. **P1-4**（等价替换、低风险）次之。
3. **P1-2** 最后，因为要进 prod 环境实跑联调，单独验证。

三条互不耦合，也可拆成三个独立 feature 分支/提交。建议提交前缀：P1-1/P1-4 用 `fix(rag)`/`fix(review)`，P1-2 用 `fix(deps)`。

---

## 附录：P1-3（pgvector ANN 索引）——本批不做，仅备查
当前 `code_chunks.embedding` 无 ivfflat/hnsw 索引，检索走全表顺扫。规模小（≤200 chunk）时顺扫更优且零调参。若未来 chunk 量级上万再考虑：
```sql
CREATE INDEX ON code_chunks USING hnsw (embedding vector_cosine_ops);
```
需配套：建索引走 alembic 迁移；hnsw 要 pgvector ≥0.5（确认服务器版本）；低数据量下别建（召回会降）。面试若被问"为什么没加向量索引"，答"当前规模顺扫即最优，加 ANN 是数据量上量后的事"即可，是合理的工程权衡而非缺陷。
