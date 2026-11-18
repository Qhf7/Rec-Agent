# 统一数据契约与 Jev 判断协议实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan.

## Global Constraints

- `data/raw/` 是唯一 canonical 数据源；商品 ID 统一为 `i_####`。
- `exposure_reason` 是唯一用户可见理由；`generated_reason` 必须与其完全一致。
- Jev 只接收当前候选的可核验事实，不接收点击历史、CTR、订单、退款、投诉、排序分或人工未来标签。
- 旧 `item_####` 候选只能经过显式校验迁移，禁止静默猜测。
- 本阶段只打通离线契约和真实 Jev 接入前的协议；不实现线上埋点、人工审核平台和生产部署。

## Review Focus

- 根目录旧候选与 `data/raw` 的 ID/字段不一致：测试候选能否直接通过 MCP `get_item(i_####)` 找回相同商品。
- 候选、Fact Bundle 和 Jev payload 的版本/ID 漂移：测试 `reason_id`、`item_id`、`data_version` 是否贯穿一致。
- Jev 输入泄漏点击历史或排序信号：测试 payload 的递归字段禁传。
- 七问协议与旧三问响应兼容：测试新 payload 和旧响应都能被明确解析，缺问不被伪装成完整协议。
- 迁移冲突和证据路径错误：测试必须失败并报告原因。

### Task 1: 建立 canonical 数据契约与加载器

**Files:**
- Create: `canonical_data.py`
- Create: `tests/test_canonical_data.py`
- Modify: `mcp_server.py`
- Modify: `data/README.md`

**Interfaces:**
- Produces `CANONICAL_SCHEMA_VERSION = "canonical-2026-06-15-v1"`。
- Produces `load_canonical_users()`, `load_canonical_items()`, `load_canonical_promos()`。
- Produces `normalize_item_id(value: str) -> str`，只把已验证的 `item_####` 转成 `i_####`。
- Produces `validate_canonical_item(item: dict) -> dict`，检查必需字段、ID 格式和金额类型。

- [ ] **Step 1: Write failing tests**
  - canonical loader 只读 `data/raw`。
  - `item_0001` 只有在标题、品牌和数字后缀都匹配时才转换。
  - 不匹配或未知 ID 抛出明确的契约错误。
  - canonical 商品可以被 `mcp_server.get_item("i_0001")` 找回。

- [ ] **Step 2: Run tests and verify RED**

  Run: `pytest tests/test_canonical_data.py -q`

- [ ] **Step 3: Implement the loader and validators**

  将现有 MCP 的 CSV/JSON 解析逻辑集中到 canonical loader；保留缓存，但把数据版本作为返回元数据。

- [ ] **Step 4: Run tests and verify GREEN**

  Run: `pytest tests/test_canonical_data.py tests/test_mcp_server.py -q`

- [ ] **Step 5: Commit**

  `git add canonical_data.py mcp_server.py data/README.md tests/test_canonical_data.py && git commit -m "feat: add canonical data contract"`

### Task 2: 迁移离线候选、Fact Bundle 和回放链路

**Files:**
- Create: `scripts/migrate_legacy_candidates.py`
- Create: `tests/test_canonical_replay.py`
- Modify: `generate_full_candidates.py`
- Modify: `generate_pilot_candidates.py`
- Modify: `fact_bundle.py`
- Modify: `generate_agent_candidates.py`
- Modify: `tests/test_full_candidates.py`
- Modify: `tests/test_fact_bundle.py`

**Interfaces:**
- Produces `migrate_legacy_candidate(row: dict) -> dict`。
- Produces `validate_candidate_contract(candidate: dict) -> dict`。
- All candidate generators emit `schema_version`, `data_version` and canonical `i_####` IDs。

- [ ] **Step 1: Write failing tests**
  - 根目录旧字段不能再作为默认读取源。
  - canonical 候选可直接构造 Fact Bundle，并从 MCP 找回同一商品。
  - 旧 `item_####` 迁移成功时保留 `reason_id`，冲突时失败。
  - provenance 只指向 `data/raw`，不出现旧根目录商品路径。

- [ ] **Step 2: Run tests and verify RED**

  Run: `pytest tests/test_canonical_replay.py tests/test_full_candidates.py tests/test_fact_bundle.py -q`

- [ ] **Step 3: Implement migration and update generators**

  默认从 canonical loader 读取用户、商品和促销；旧数据只通过显式迁移脚本进入，迁移时校验标题、品牌、后缀和数据版本。

- [ ] **Step 4: Run tests and replay a sample**

  Run: `pytest tests/test_canonical_replay.py tests/test_full_candidates.py tests/test_fact_bundle.py -q`

  Run: `python3 generate_pilot_candidates.py --help`

- [ ] **Step 5: Commit**

  `git add generate_full_candidates.py generate_pilot_candidates.py generate_agent_candidates.py fact_bundle.py scripts/migrate_legacy_candidates.py tests/test_canonical_replay.py tests/test_full_candidates.py tests/test_fact_bundle.py && git commit -m "refactor: replay candidates through canonical data"`

### Task 3: 落地 Jev 七问协议和输入白名单

**Files:**
- Create: `jev_protocol.py`
- Create: `tests/test_jev_protocol.py`
- Modify: `jev_adapter.py`
- Modify: `fact_bundle.py`
- Modify: `tests/test_jev_adapter.py`
- Modify: `推荐理由曝光审核-项目基线与技术方案.md`

**Interfaces:**
- Produces `JEV_QUESTION_SCHEMA_VERSION = "jev-questions-v1"`。
- Produces `build_jev_questions() -> dict`，固定 Q1–Q7 的问题、类型、选项和判定标准。
- Produces `build_jev_input(fact_bundle: dict) -> dict`，只输出允许字段。
- Produces `validate_jev_input(payload: dict) -> dict`。
- Produces `parse_jev_answers(payload: dict, fact_bundle: dict) -> dict`，兼容旧三问响应并标记 `protocol_completeness`。

- [ ] **Step 1: Write failing tests**
  - Q1–Q7 全部存在且选项固定。
  - payload 包含商品事实、商业快照、场景摘要、证据和版本。
  - payload 递归排除 history、CTR、订单、退款、投诉、排序分、搜索词和购物车。
  - 非法证据路径、缺失版本、缺失 reason/item ID 失败。
  - 旧三问响应仍可解析，但标记为兼容协议而不是完整七问。

- [ ] **Step 2: Run tests and verify RED**

  Run: `pytest tests/test_jev_protocol.py tests/test_jev_adapter.py -q`

- [ ] **Step 3: Implement protocol and adapter integration**

  `JevAdapter.build_payload()` 改为使用七问协议；保留 `answers.decision`、`answers.risk_type`、`answers.judge_score` 的旧解析路径。事实冲突或不可验证状态优先升级 `human_review`。

- [ ] **Step 4: Run tests and verify GREEN**

  Run: `pytest tests/test_jev_protocol.py tests/test_jev_adapter.py -q`

- [ ] **Step 5: Commit**

  `git add jev_protocol.py jev_adapter.py fact_bundle.py tests/test_jev_protocol.py tests/test_jev_adapter.py 推荐理由曝光审核-项目基线与技术方案.md && git commit -m "feat: add Jev seven-question protocol"`

### Task 4: 端到端离线回放、文档和全量验证

**Files:**
- Create: `tests/test_end_to_end_canonical_jev.py`
- Modify: `README.md`
- Modify: `测试方案-Rec-Agent与Jev链路.md`
- Modify: `harness-main-workspace.md`

- [ ] **Step 1: Write failing end-to-end tests**
  - canonical candidate → Fact Bundle → Jev payload → dry-run request 全链路保持 ID/版本一致。
  - Jev payload 没有用户反馈历史。
  - blocked、unverifiable、rewriteable 三种状态分别走预期处置。

- [ ] **Step 2: Run the focused test and verify RED**

  Run: `pytest tests/test_end_to_end_canonical_jev.py -q`

- [ ] **Step 3: Implement documentation and command corrections**

  更新本地运行步骤、七问输入说明、canonical 数据路径和旧候选迁移命令；修正测试方案中过时的 `--dry-run --input` 示例。

- [ ] **Step 4: Run all verification commands**

  Run: `pytest -q`

  Run: `python3 scripts/validate_data.py`

  Run: `python3 -m compileall canonical_data.py jev_protocol.py mcp_server.py fact_bundle.py jev_adapter.py`

- [ ] **Step 5: Commit**

  `git add README.md 测试方案-Rec-Agent与Jev链路.md harness-main-workspace.md tests/test_end_to_end_canonical_jev.py && git commit -m "test: verify canonical Jev replay"`

## Execution Order

按 Task 1 → Task 2 → Task 3 → Task 4 顺序执行。Task 2 依赖 Task 1 的 loader 和 ID 校验；Task 3 依赖 Task 2 的稳定 Fact Bundle；Task 4 依赖前三项的接口。

## Completion Criteria

- `pytest -q` 全部通过。
- `scripts/validate_data.py` 通过。
- 任意 canonical 离线候选都能被 MCP 和 Fact Bundle 读取，不再依赖根目录旧商品表。
- Jev payload 固定为七问协议，旧三问响应仍能安全兼容。
- 任何点击历史、CTR、订单、退款、投诉和排序信号都不会进入 Jev payload。
