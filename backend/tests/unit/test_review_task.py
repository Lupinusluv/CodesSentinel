"""Unit tests for _parse_issues — the most fragile part of the MVP pipeline."""

import pytest

from app.tasks.review_task import _parse_issues


VALID_RESPONSE = """\
## Part 1 — Narrative

Some review text here.

## Part 2 — Structured JSON

```json
[
  {
    "category": "security",
    "severity": "critical",
    "line_start": 5,
    "line_end": 7,
    "description": "SQL injection via string concatenation.",
    "suggestion": "Use parameterized queries."
  },
  {
    "category": "performance",
    "severity": "warning",
    "line_start": 12,
    "line_end": 12,
    "description": "O(n^2) string concatenation in loop.",
    "suggestion": "Use str.join()."
  }
]
```
"""

NO_JSON_BLOCK = """\
## Review

Everything looks fine, no issues found.
No structured block here at all.
"""

MALFORMED_JSON = """\
Some text.

```json
{ this is not valid json [
```
"""

OPTIONAL_FIELDS_OMITTED = """\
```json
[
  {
    "category": "style",
    "severity": "suggestion",
    "description": "Variable name too short."
  }
]
```
"""

MULTIPLE_BLOCKS_USES_LAST = """\
Here is an example block that should be ignored:

```json
[{"category": "security", "severity": "critical", "description": "ignore me"}]
```

And here is the real one:

```json
[
  {
    "category": "style",
    "severity": "suggestion",
    "description": "Use consistent naming.",
    "suggestion": "Follow PEP 8."
  }
]
```
"""


def test_parses_valid_response():
    issues = _parse_issues(VALID_RESPONSE)
    assert len(issues) == 2
    assert issues[0].category.value == "security"
    assert issues[0].severity.value == "critical"
    assert issues[0].line_start == 5
    assert issues[1].category.value == "performance"


def test_no_json_block_returns_empty():
    issues = _parse_issues(NO_JSON_BLOCK)
    assert issues == []


def test_malformed_json_returns_empty():
    issues = _parse_issues(MALFORMED_JSON)
    assert issues == []


def test_optional_fields_can_be_omitted():
    issues = _parse_issues(OPTIONAL_FIELDS_OMITTED)
    assert len(issues) == 1
    assert issues[0].line_start is None
    assert issues[0].suggestion is None
    assert issues[0].severity.value == "suggestion"


def test_uses_last_json_block_when_multiple():
    issues = _parse_issues(MULTIPLE_BLOCKS_USES_LAST)
    assert len(issues) == 1
    assert issues[0].description == "Use consistent naming."


def test_empty_string_returns_empty():
    assert _parse_issues("") == []
