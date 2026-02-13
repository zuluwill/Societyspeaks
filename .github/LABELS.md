# Suggested GitHub Labels

This document defines a simple label taxonomy to keep issue triage consistent as contributor activity grows.

## Priority

- `priority: critical` - production outage, security incident, or data risk
- `priority: high` - major user impact, should be addressed soon
- `priority: medium` - important but not urgent
- `priority: low` - minor impact or nice-to-have

## Type

- `bug` - incorrect behavior or regression
- `enhancement` - improvement to existing behavior
- `feature` - net-new capability
- `docs` - documentation only
- `security` - vulnerability or hardening work
- `refactor` - code quality or structure change with no intended behavior change
- `performance` - speed, latency, memory, or scale improvements

## Area

- `area: api`
- `area: partner`
- `area: embed`
- `area: discussions`
- `area: briefs`
- `area: auth`
- `area: admin`
- `area: infrastructure`
- `area: frontend`
- `area: docs`

## Workflow

- `good first issue` - suitable for first-time contributors
- `help wanted` - maintainers want community support
- `needs repro` - report requires a reproducible case
- `needs info` - waiting on reporter details
- `blocked` - dependent on another task
- `wontfix` - acknowledged but not planned
- `duplicate` - covered by an existing issue

## Suggested Triage Rules

1. Every issue gets one `type` label.
2. Add one `area` label where possible.
3. Add one `priority` label for planning.
4. Use workflow labels to show status clearly.
