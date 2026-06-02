# 架构 + 测试审计报告 — 2026-06-02

> 本会话职责：架构和测试。应用户「先审计、再定方向」的决策，对全后端 + 关键约束做一轮静态审计 + 测试基线核验，产出**排好序的质量清单**，供后续「编写代码」会话执行。
> 读法：先看本文 §3 清单；§1 是测试实况、§2 是总体判断、§4 是对 backlog 排序的修正建议。

---

## 1. 测试基线核验（实测，非引用记忆）

本机 `backend/venv` 跑 `pytest tests/ -q`（无 test DB）：

```
65 passed, 35 skipped, 16 warnings in 146s
```

- 记忆里的「100 passed」**依赖 `codessentinel_test` 库在跑**；无 DB 时 35 个集成测试（webhook happy-path、v0.4.5 的 500-bug 回归、from_dsn 入队/消费）会被 conftest 自动 **skip**。
- **结论**：当前没有任何环境在自动跑这 35 个最贴近线上行为的回归——本地默认不带 DB，且**仓库无 CI**（`.github/workflows` 不存在）。"100 passed" 是「我机器上手动起了 DB 才成立」的口径，不是护栏。
- 16 条 warning 全是 pydantic v1 `ForwardRef._evaluate` 的 DeprecationWarning（三方库，非本仓代码），暂不阻塞。

---

## 2. 总体判断

代码质量其实**高于用户自评的「70 分」**。值得肯定的事实（审计中逐一读码确认）：

- **架构约束被严格遵守**：adapter / agent / task 三层副作用隔离到位——Agent 节点只改 `ReviewState`，DB 读写与 GitHub 回调全部收敛在 `review_task.py`；平台调用一律走 `GitPlatformAdapter`。
- **错误处理普遍 fail-soft**：RAG embedding 失败吞异常返 ""（审查不崩）、GitHub 回调失败只 warning 不污染主任务、AutoFix LLM 异常/空输出/语法不过都降级为 `failed` 而非抛栈。
- **两个历史坑已用稳的方式修掉**：HMAC 用 `hmac.compare_digest`（时序安全）；图终态判定用 `not parent_ids` 而非硬编码 `name=="LangGraph"`（抗 langgraph 改名）。
- `WorkerSettings.job_timeout=600` 给了挂死 LLM 一个上界，`_EMBED_BATCH=10` 与 DashScope 单请求上限对齐。

真正的扣分项**不在「写得对不对」**，集中在三块：① 一个确定的质量 bug（④ 去重）；② 「真产品 / 冲星」维度的工程完备性缺口（无 CI、验签 fail-open、占位适配器、版本号）；③ 表层观感（i18n / README）。下面按可执行项排序。

---

## 3. 排序质量清单

### P0 — 确定性缺陷，先修

**① ④ report 去重 lane-bleeding**（纯后端，半天，交「编写代码」）

- 位置：`backend/app/agents/synthesis_agent.py:46 deduplicate_issues`。`synthesis_node` 与 `review_task.py:107` 写库前**复用同一个函数**（不是交接说的两处独立实现——只有一个修改点，更干净）。
- 病根：key = `(file_path, line_start, category)`。于是两类重复漏网：
  - **跨类别**：同一行的同一问题被 security 与 style 各报一次、category 不同 → 两条 key 不同 → 都留下。
  - **行号±1 漂移**：同一问题一个 Agent 标 L41、另一个标 L42 → key 不同 → 都留下。
- 实锤：`synthesis_done deduped=18 raw=20`——20 条只去掉 2 条（仅命中完全相同的三元组）。
- 修法（**经团队「资深开发」修正后的最终规格**——原案"无条件跨类别聚合"会误并真不同的问题，已收敛）：
  - **档位 1（零误并风险，必做）**：同 file + **同 category** + `|Δline|≤2` 才聚合。±2 是经验安全带（diff 行号 vs 绝对行号常差 ±1）；**不要 ≤5**（会把相邻独立函数的问题并掉）。这一档已能吃掉 `raw=20 deduped=18` 漏网的大部分。
  - **档位 2（跨类别，需加约束）**：跨 category 仅当 `description` 文本相似度高才并（粗糙做法：归一化后 token Jaccard ≥ 0.6 或子串包含）。**不能只靠行号跨类别合并**——否则会把"同一行的 SQL 注入(critical) + 字符串拼接低效(warning)"这两个真问题误并。
  - **不做**"区间相交"（line_end 常为 None 或 LLM 乱填，会放大误并）。
  - line_start 为 None（whole-file）退化为按 file 聚类，但**异义不并**（现有测试只覆盖了同义合并，缺异义不合并的护栏）。聚合后排序仍按 severity，且需 stable 排序（否则报告 issue 顺序每跑每抖、截图对不上、测试 flaky）。
- **⚠️ 落地必读**：现有 `tests/unit/test_synthesis_agent.py` 有一条 `test_same_line_different_category_keeps_both` 断言**相反行为**（同行不同类保留 2 条）。档位 2 会让它变红——这条是**要修改的测试**，不是 bug。只加新用例不改旧用例会陷入"两测试互相矛盾、怎么都绿不了"。
- **可直接落地的失败用例 repro**（交「编写代码」会话先写成 test，红 → 改 → 绿）：

  ```python
  # tests/unit/test_dedup.py
  def test_dedup_collapses_cross_category_adjacent_lines():
      issues = [
          IssueOutput(category=IssueCategory.security, severity=IssueSeverity.critical,
                      file_path="a.py", line_start=41, description="SQL injection"),
          IssueOutput(category=IssueCategory.style, severity=IssueSeverity.warning,
                      file_path="a.py", line_start=42, description="same spot, other lane"),
      ]
      out = deduplicate_issues(issues)
      assert len(out) == 1            # 现状会得到 2 —— 这就是 lane-bleeding
      assert out[0].severity == IssueSeverity.critical   # 保最高 severity
  ```

  > 注意：放宽聚合**有误并风险**（把两个真不同的问题并成一个）。需同时补一个「同 file 但行号相距远 / 真不同问题」必须保留两条的反向用例，防止改过头。

### P1 — 「真产品 / 冲星」工程完备性，冲星前必补

**② 加 CI（GitHub Actions）** — 工作量小、冲星硬通货

- 现状无 `.github/workflows`。加一个 workflow：起 postgres service → `alembic upgrade head` → `pytest tests/`（让那 35 个集成测试**真正在 CI 里带 DB 跑**）+ `npx tsc --noEmit`。
- 双重收益：README 顶部一个绿 ✅ badge 是 star 转化的标配；同时堵住 §1 那个「回归无护栏」的窟窿。
- **⚠️ 让 35 个 skip 测试真跑起来的三个静默陷阱（经「资深开发」核实 conftest 机制后补全，缺一即全 skip → CI 绿但啥都没测，比红更危险）**：
  1. **必须用 `pgvector/pgvector:pg16` 镜像**，不能用官方 `postgres`——schema 有 vector 列，alembic 迁移会 `CREATE EXTENSION vector` 失败。
  2. **必须手动建 `codessentinel_test` 库**——conftest 连的是 `codessentinel_test`，而 compose 的默认库名是 `codessentinel`，名字不一样；conftest 的 skip 判据就是"能不能连上这个 test 库"（跑 `SELECT 1`，连不上就 skip）。
  3. **`CREATE EXTENSION vector` 需要超级用户**——GitHub Actions 的 postgres service 默认 `postgres` 超级用户，直接用它跑 alembic 最省事，别为了拟真建低权限 app 用户。
- **redis service 对当前测试集非必需**（35 个集成测试用 `fake_arq` AsyncMock，不连真 redis），留着无害、为未来 from_dsn 真连测试备用。
- **无 Windows-only 测试坑**（已逐个核实：`_check_node` 在 Linux 兼容、node 不在 PATH 会降级为通过、无盘符/`\r\n`/`os.name` 依赖）。
- **`black --check` 不进 CI 初版**：black 不在 requirements、仓库从没跑过（见 [[feedback_black_never_enforced]]），初版加它必全红。顺序＝**先全仓 black 一次性格式化（P2-⑥）→ 再给 CI 补 `black --check`**。（修正本文档早先把 `black --check` 写进 CI 初版的自相矛盾。）

**③ Webhook 验签 fail-open → fail-closed**（安全，reviewer 一眼会挑）

- `webhooks.py:84`：`github_webhook_secret` 为空时**完全跳过验签**。任何人都能 POST 伪造 webhook 触发审查 → 烧 LLM token / 入队 DoS。
- 当前生产 secret 已配，所以「现在不出事」，但这是**设计上 fail-open**。建议：`app_env=production` 且 secret 为空时启动即报错（pydantic validator / lifespan 启动检查，比端点级 if 更早暴露问题），dev 下保持放行（本地 ngrok 测真 webhook 依赖空 secret）。
- **🔴 顺带修一个比 fail-open 更根本的设计 bug（「资深开发」读码挖出，审计初版漏掉）+ 已拍板处理方式**：`Repository` 模型有 `webhook_secret` 字段（NOT NULL, 128），注册仓库时也填了值，但 `webhooks.py:84` 验签**只用全局 `settings.github_webhook_secret`，从不读每仓 secret**——那列是**死字段**。且验签发生在查库**之前**（控制流：先验签→再 `select Repository`），想用每仓 secret 得重构成"先解析 payload 拿 repo_url→查库→用该仓 secret 验签"。
  - **定案（用户拍板 2026-06-02）：删字段，承认 MVP 用单个全局 secret。** 删掉 `Repository.webhook_secret` 列（含 alembic 迁移），消除"建了列却不用"的虚报观感。理由：当前单 demo 仓体量，每仓 secret 属过度设计；面试讲"MVP 单租户取舍"。**与本项（验签 fail-closed）同一批做。**

**④ 占位适配器名不副实**

- `gitlab.py` / `gitee.py` 是 **0 字节空文件**，对应 webhook 端点返 501，但 SPEC/README/CLAUDE 都宣称「平台无关 GitHub/GitLab/Gitee」。reviewer 会觉得虚报（踩过 sandbox/BM25 同类教训）。
- 两条路选一：要么落地一个适配器（原 backlog ②，顺便展示 `GitPlatformAdapter` 抽象的价值），要么 README 明确标注 GitLab/Gitee 为 roadmap、未实现。**先选便宜的：README 标注**；想加分再实现。

### P2 — 低风险打磨

- **⑤ 版本号**：`main.py:30,51` 仍 `0.1.0`，项目已 v0.5.2。对齐它（顺手把版本抽成单一常量，别两处硬编码）。
- **⑥ 全仓 Black chore**：单独批次，别混功能提交（见记忆 [[feedback_black_never_enforced]]）。最好等 ② CI 把 `black --check` 接上后一起做。
- **⑦ `parse_agent_json` 静默吞错**：`utils.py:24` 任何 JSON 解析失败 → 返 `[]`，该 Agent 这次「零 issue」只留一条 warning。低频但会无声漏报。建议至少把解析失败计入 metrics；进阶做一次 repair 重试。
- **⑧ `embed_texts` 不内部分批**：`embeddings.py` 依赖每个调用方自己切 ≤10（目前 index_task 切了、retriever 单条，安全）。防御性地在函数内分批，避免未来新调用方踩 400。优先级低。

---

## 4. 团队评审与最终定案（2026-06-02，已拍板，**本节为权威执行规格，覆盖审计初版排序**）

审计初版排序被拉来「资深开发」+「产品/秋招」两个角色评审，二者**都反对原排序**，收敛结论：

- **审计初版是「工程师排序」，对冲星是优先级倒置**——去重/CI/验签路人全看不见。冲星发生在「README 首屏 5 秒 + 视觉证据」，而项目有公网 demo `https://tantai.xyz`，README 里却**没放任何 demo 链接**（审计初版整份漏列呈现层）。
- **去重该做但不该排第一**（不阻塞、看不见）；**CI 是唯一同时砸中冲星(绿 badge)+秋招(最强面试故事:"加 CI 才发现 35 个集成测试一直静默 skip")+质量(回归护栏)的项**，应靠前。
- 去重算法、CI 三陷阱、per-repo secret 三处已在 §3 就地修正。

### 定案：双轨并行

**A 轨 — 呈现层（零代码，立刻，归「架构和测试」会话 + 用户推；不阻塞 B 轨）**

| 项 | 内容 |
|---|---|
| A1 | README 首屏重写 + `https://tantai.xyz` 置顶 + "Try it, no setup" 指向 paste 模式 |
| A2 | 一张真架构图 + 10 秒产品 GIF（粘代码→3 Agent 流式→synthesis→AutoFix diff） |
| A3 | README 把 GitLab/Gitee 明确标为 **roadmap/未实现**（用户拍板：**只标 roadmap，不实现**，消除虚报）+ `main.py` 版本号 0.1.0 → 对齐 0.5.2（抽成单一常量） |

**B 轨 — 代码（交「编写代码」会话，按工程风险排批次）**

| 批次 | 内容 | 提交粒度 | 工时 |
|---|---|---|---|
| B1 | **CI**（pgvector service + 建 `codessentinel_test` 库 + alembic + 全量 pytest + tsc，**初版不含 black**）+ 顶部 badge | 独立 `chore:` | ~5h |
| B2 | **④ 去重**（§3① 收敛算法：同类邻近无条件并 + 跨类别需描述相似才并）+ 正反向用例 + **改 `test_same_line_different_category_keeps_both`** | 独立 `fix:` | 3–4h |
| B3 | **全仓 black 一次性格式化 → 再给 CI 补 `black --check`** | 独立 `chore: black` | ~2h |
| B4 | **验签 fail-closed**（production 空 secret 启动即报错，dev 放行）+ **删 `Repository.webhook_secret` 死字段**（用户拍板"用全局"，含 alembic 迁移） | 独立 `fix(security):` | 2–3h |
| B5 | `parse_agent_json` 漏报信号（§3⑦ 升级版：ReviewState 加 `parse_failures` 计数，done 事件带上，前端可提示"某 Agent 分析异常"） | `fix:` | ~2h |
| B6 | i18n（**降级**：先用"demo 界面英文优先"拿走 80% 收益，完整 i18n 框架最后） | 独立 | 前端为主 |

**已砍/不做**：GitLab/Gitee 适配器真实现（用户拍板只标 roadmap）；区间相交去重；embed_texts 内部分批（§3⑧，当前安全，优先级最低，见缝插针）。

### 决策记录（用户 2026-06-02 拍板）

1. **总方案**：双轨并行、A 轨零代码立刻做、B 轨第一批是 CI 而非去重 → ✅ 准。
2. **per-repo secret 矛盾** → ✅ 删字段，用全局（MVP 单租户取舍）。
3. **GitLab/Gitee 适配器** → ✅ 只标 roadmap，不实现。

**一句话**：A 轨（README+demo 链接+GIF）今天就能并行起步、零代码、冲星 ROI 最高；B 轨代码第一批是 CI（兜住回归 + 拿 badge + 最强面试故事），再去重、再 black、再验签收敛。i18n 降级、适配器只标 roadmap。
