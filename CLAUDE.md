@AGENTS.md

## Claude Code specifics

- The person is experienced in Python and new to dbt: explain each new dbt concept when it
  first appears, and don't over-explain Python.
- Mechanical, already-specified changes go to the `implementer` subagent (user-level, named
  in `.agentic/config.toml`). Design, data semantics and judging real-season numbers stay
  in the main session.
- Workflow skills (`spec`, `adr`, `build`, `review-loop`) read `.agentic/config.toml`.
