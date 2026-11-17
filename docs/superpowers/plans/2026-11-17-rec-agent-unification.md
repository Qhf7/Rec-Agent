# Rec-Agent Main Workspace Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify the Rec-Agent data, preset, MCP tools, and Harness profile under the main Jev exposure-review workspace while adding an explicit user-facing `exposure_reason` field.

**Architecture:** Keep existing root Jev artifacts unchanged. Add the canonical mock data under `data/`, copy the Harness preset into `rec-agent-preset/`, expose read-only FastMCP tools from `mcp_server.py`, and make `generated_reason` a compatibility alias of `exposure_reason`.

**Tech Stack:** Python 3, FastMCP, CSV/JSON/SQLite, pytest, DeepSeek Harness profile bundle.

**Spec:** `docs/superpowers/specs/2026-11-17-rec-agent-unification-design.md`

## Global Constraints

- All mock data remains fictional and must not contain real user or production data.
- MCP tools are read-only and must not call Jev or mutate workspace files.
- `exposure_reason` is one user-facing Chinese sentence with at most 24 Chinese characters.
- `generated_reason` remains equal to `exposure_reason` for downstream compatibility.
- Jev fields remain outside the Rec-Agent output contract.

## Review Focus

- Unknown `user_id`: return an explicit empty result instead of inventing a profile; test in `tests/test_mcp_server.py`.
- Unknown `item_id` and inactive promotion: return structured absence; test in `tests/test_mcp_server.py`.
- User-facing text contamination: `exposure_reason` must not contain evidence or context fields; test in `tests/test_rec_agent_contract.py`.
- Data root drift: MCP tools must resolve paths relative to the main workspace; test by importing from the repository root.
- Harness compatibility: `generated_reason` and `exposure_reason` must both exist and be equal in the preset contract; test in `tests/test_rec_agent_contract.py`.

### Task 1: Define failing MCP and output-contract tests

**Files:**
- Create: `tests/test_mcp_server.py`
- Create: `tests/test_rec_agent_contract.py`

- [ ] Write tests for profile, behavior, item search, and promotion queries.
- [ ] Run `pytest tests/test_mcp_server.py tests/test_rec_agent_contract.py -q` and confirm failure because the new module/data/preset are absent.

### Task 2: Sync canonical data and preset

**Files:**
- Create: `data/` from the verified `_副本/data/` source
- Create: `rec-agent-preset/` from the verified `_副本/rec-agent-preset/` source
- Modify: `rec-agent-preset/README.md`
- Modify: `rec-agent-preset/cordis.patch.yml`

- [ ] Copy data and preset without overwriting root Jev artifacts.
- [ ] Add `exposure_reason` to the JSON schema and make `generated_reason` its compatibility alias.
- [ ] Rewrite the prompt so `exposure_reason` contains only the user-facing sentence; keep evidence and context internal.

### Task 3: Implement read-only FastMCP tools

**Files:**
- Create: `mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] Implement `get_user_profile`, `get_user_behavior`, `get_session_context`, `get_item`, `search_items`, and `get_promo` against `data/raw/` and `data/mock.db`.
- [ ] Run the focused tests and confirm they pass.

### Task 4: Point the Harness profile at the main workspace

**Files:**
- Modify: `~/.dsh/profiles/desktop/package.json` (local runtime configuration)
- Create: `harness-main-workspace.md`

- [ ] Change the local bundle link from `_副本/rec-agent-preset` to the main workspace `rec-agent-preset`.
- [ ] Document the new workspace path, MCP launch command, and sample input.

### Task 5: Full verification

- [ ] Run `python3 scripts/validate_data.py` from `data/`.
- [ ] Run the full `pytest -q` suite.
- [ ] Parse the preset YAML and assert the new output contract.
- [ ] Verify the profile link and bundle name point to the main workspace.
