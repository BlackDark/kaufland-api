# kaufland-api

Python CLI and API for downloading Kaufland receipts and exporting JSON, HTML, JPG, and PDF.

## Verify

`mise run check`: frozen uv environment, Ruff, and pytest.

CI uses the same command plus actionlint, zizmor, and strict Renovate validation. The required gate is `check`.

## Stack

Follows https://github.com/BlackDark/agent-presets/blob/main/stack/core.md. The existing hatchling, uv, requests, Playwright, Ruff, and pytest stack stays.

## Map

- `kaufland_api/`: CLI, API client, archive, and exporters.
- `tests/`: offline receipt tests.
- `pyproject.toml`, `uv.lock`: package and exact environment.

## Git

- Conventional Commits, one topic per PR.
- Squash unless commits need separate review.
- Force-push only with `--force-with-lease` on own branches.

## Boundaries

- Tools come from `mise.toml`; no global installs.
- Do not use personal Kaufland credentials or live account data in tests.
- Do not publish packages or create release tags from a local session.
