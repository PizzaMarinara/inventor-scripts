# Codebase Analysis Report — `inventor-scripts`

**Date:** 2026-03-27
**Files analyzed:** 18 Python source/test files
**Analyzer:** SocratiCode + Claude

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 1 |
| High | 6 |
| Medium | 8 |
| Low | 5 |
| **Total** | **20** |

---

## CRITICAL

### C1. Missing `Any` import in `web.py`
- **File:** `web.py:43`
- **Type:** Import Error / Bug
- **Description:** `Any` is used in a type annotation (`loop: Any | None = None`) but never imported from `typing`. This causes a `NameError` at module load, breaking the entire web UI.
- **Fix:** Add `from typing import Any` to the imports.

---

## HIGH

### H1. Path Traversal Vulnerability in Download Endpoint
- **File:** `web.py:86-92`
- **Type:** Security
- **Description:** The `download_file` endpoint constructs a path via `Path.cwd() / "output" / filename` with unsanitized user input. A request with `filename=../../../etc/passwd` could expose arbitrary files on the system.
- **Fix:**
  ```python
  output_dir = Path.cwd() / "output"
  resolved = (output_dir / filename).resolve()
  if not resolved.is_relative_to(output_dir.resolve()):
      raise HTTPException(status_code=400, detail="Invalid filename")
  ```

### H2. Race Condition in Session Management
- **File:** `web.py:231-240`
- **Type:** Concurrency Bug
- **Description:** The check `active_session is None` and its subsequent assignment are not atomic. Two concurrent WebSocket connections can both pass the check and create duplicate sessions simultaneously, corrupting shared document state.
- **Fix:** Guard the check-and-set with `asyncio.Lock`.

### H3. History Mutation Bug in Agent Loop
- **File:** `agent/loop.py:288`
- **Type:** Logic Bug / State Management
- **Description:** When max iterations is reached, `self._history = list(messages)` stores all messages including the new user turn — but without an assistant response to close that turn. On the next call, `self._history` is prepended again, duplicating prior turns and producing corrupted conversation history where the LLM sees incomplete exchanges.
- **Fix:** Only store completed exchanges. On max-iteration exit, discard the in-progress user turn or explicitly append a sentinel assistant message.

### H4. Silent Exception Swallowing in `extract.py`
- **File:** `extract.py:47-62`
- **Type:** Error Handling
- **Description:** Bare `except Exception: pass` blocks mask genuine COM failures. Expected missing-collection errors are indistinguishable from real errors, making debugging impossible.
- **Fix:** Log a warning for unexpected exceptions; only silently pass for well-understood expected cases (e.g., `AttributeError` on absent collections):
  ```python
  except AttributeError:
      pass  # expected: collection doesn't exist
  except Exception as e:
      logger.warning("Unexpected error extracting parameters: %s", e)
  ```

### H5. Subprocess Environment Leak in `agent/llm.py`
- **File:** `agent/llm.py:221-223`
- **Type:** Security
- **Description:** Only `ANTHROPIC_API_KEY` is stripped from the subprocess environment. Other sensitive variables present in the parent process (e.g., `DATABASE_PASSWORD`, cloud credentials) are still inherited by the subprocess.
- **Fix:** Use an allowlist instead of a denylist — pass only `PATH`, `HOME`, `TEMP`, `PYTHONPATH`, and other explicitly required variables.

### H6. `Path.cwd()` Evaluated in Worker Thread
- **File:** `web.py:129`
- **Type:** Bug
- **Description:** `Path.cwd()` is called inside a blocking thread. Thread working directories can differ from the main thread's, causing file lookups to fail unpredictably.
- **Fix:** Capture `cwd = Path.cwd()` in the main thread before spawning the worker, then pass it as an argument.

---

## MEDIUM

### M1. Test-to-Code Mismatch — Download Endpoint
- **File:** `tests/test_web.py:57` vs `web.py:92`
- **Type:** Test Inconsistency
- **Description:** The test asserts `resp.json() == {"ok": True}`, but the endpoint returns a `FileResponse` (binary content). The test passes vacuously without validating real download behavior.
- **Fix:** Assert `resp.content == expected_file_bytes` and check the `Content-Type` header.

### M2. Hardcoded Italian in Error Messages
- **Files:** `main.py:56-58`, `web.py:134-137`, `agent/llm.py:242-257`
- **Type:** Localization Inconsistency
- **Description:** Error messages are written in Italian while all code, comments, and documentation are in English. This is inconsistent and makes logs hard to parse in mixed environments.
- **Fix:** Use English for all error messages. If multilingual support is needed, implement a proper i18n system.

### M3. Missing Input Validation in `modify.py` — `add_component`
- **File:** `modify.py:207-209`
- **Type:** Missing Validation
- **Description:** `translation_mm` is accepted as a list but not validated for length (must be exactly 3) or element types. Invalid input surfaces as a cryptic COM error rather than a clear validation error.
- **Fix:**
  ```python
  if translation_mm and (
      len(translation_mm) != 3
      or not all(isinstance(x, (int, float)) for x in translation_mm)
  ):
      raise ValueError("translation_mm must be a list of 3 numbers [x, y, z]")
  ```

### M4. Missing Error Handling in `modify.py` — `save_as`
- **File:** `modify.py:111`
- **Type:** Missing Error Handling
- **Description:** `doc.SaveAs(str(dest), save_copy_as)` is called without a try-except. COM failures (locked file, insufficient permissions) propagate as raw unformatted exceptions.
- **Fix:** Wrap in try-except and raise a clear user-facing message.

### M5. Incorrect `Request` Import in `web.py`
- **File:** `web.py:22`
- **Type:** Code Smell / Import Issue
- **Description:** `Request` is imported from `fastapi.requests` (non-canonical path). The correct canonical import is `from fastapi import Request`. The import may also be unused if the route handler doesn't actually need the request object.
- **Fix:** Change to `from fastapi import Request` or remove if unused.

### M6. Hardcoded `max_tokens` in `agent/llm.py`
- **File:** `agent/llm.py:84`
- **Type:** Magic Number / Configuration
- **Description:** `"max_tokens": 4096` is hardcoded. Complex tool responses may be truncated without any visible warning.
- **Fix:** Make configurable via constructor parameter or `MAX_TOKENS` environment variable with `4096` as default.

### M7. Inconsistent Error Message Format in `modify.py`
- **File:** `modify.py:54-56, 62, 148-149, 233, 259`
- **Type:** Inconsistency
- **Description:** Some error messages include full context (occurrence path, parent label); others are bare strings with no context. This creates an inconsistent UX.
- **Fix:** Standardize to a format like `"<Operation> failed: <entity> '<name>' not found in '<parent>'"`.

### M8. No Logging in `web.py` — `_stream_events`
- **File:** `web.py`
- **Type:** Observability
- **Description:** The critical streaming/agent execution path has no server-side logging. When errors occur in production, there is no record of what happened.
- **Fix:** Add `logger = logging.getLogger(__name__)` and log at key points: function entry, tool calls, errors, and session lifecycle events.

---

## LOW

### L1. Public API Exposes Internal Recursion Parameters — `extract.py`
- **File:** `extract.py:99-100`
- **Type:** API Design
- **Description:** `extract_occurrences` is a public function but accepts `_prefix` and `_depth` as internal recursion parameters. External callers can accidentally corrupt recursive state, and the underscore convention is misleading (not truly private).
- **Fix:** Extract to a private helper `_extract_occurrences_impl(node, prefix, depth)` called internally.

### L2. Potential Empty Assistant Message in `agent/loop.py`
- **File:** `agent/loop.py:236`
- **Type:** Fragile Code
- **Description:** If both `response.assistant_content` and `response.text` are empty, an empty string is appended to history, potentially confusing the LLM on future turns.
- **Fix:** Validate that at least one of the two fields is non-empty before appending; raise or log if both are absent.

### L3. BOM Row Assumes First Component Definition is Canonical
- **File:** `extract.py:83`
- **Type:** Fragile Assumption
- **Description:** `row.ComponentDefinitions.Item(1)` assumes exactly one component per BOM row. Multi-component rows (edge case in assemblies) would return incorrect part names silently.
- **Fix:** Validate that `Item(1)` exists; handle or log multi-component rows explicitly.

### L4. Misleading System Prompt in `agent/loop.py`
- **File:** `agent/loop.py:51-52`
- **Type:** Documentation / Reliability
- **Description:** The system prompt instructs the model not to call `describe_model` again if already called, but there is no enforcement mechanism — this relies entirely on LLM memory, which is unreliable across long conversations.
- **Fix:** Track tool call history explicitly and filter it out of the tool list after first use, or remove the instruction from the prompt.

### L5. Missing Return Type Hints in `utils.py`
- **File:** `utils.py`
- **Type:** Code Quality
- **Description:** `ensure_dirs()` and `write_json()` lack `-> None` return type annotations, making the API surface incomplete for type checkers.
- **Fix:** Add `-> None` to both function signatures.

---

## Recommended Fix Order

| Priority | Issue | Effort |
|----------|-------|--------|
| 1 | **C1** — Add `from typing import Any` to `web.py` | Trivial |
| 2 | **H1** — Fix path traversal in download endpoint | Low |
| 3 | **H2** — Add `asyncio.Lock` to session management | Low |
| 4 | **H3** — Fix history mutation in agent loop | Medium |
| 5 | **H5** — Sanitize subprocess environment | Low |
| 6 | **H4** — Add logging to exception handlers in `extract.py` | Low |
| 7 | **H6** — Capture `cwd` in main thread | Trivial |
| 8 | **M1** — Fix download endpoint test | Low |
| 9 | **M2** — Replace Italian error messages with English | Low |
| 10 | **M3** — Validate `translation_mm` in `add_component` | Low |
| 11 | **M4** — Add error handling to `save_as` | Low |
| 12 | **M6** — Make `max_tokens` configurable | Low |
| 13 | **M8** — Add logging to `web.py` streaming path | Medium |
| 14 | **L1-L5** — Low-priority quality improvements | Varies |
