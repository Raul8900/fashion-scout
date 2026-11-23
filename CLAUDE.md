# Fashion Scout repo

- This repo is a personal shopping scout. The procedure lives in `.claude/skills/fashion-scout/SKILL.md`; follow it for any weekly or on-demand run.
- `profile/profile.toml` holds the user's private details (sizes, email). Never paste it into external services or web searches; search with generic terms ("men's corduroy overshirt cotton India").
- Never recommend a product that has not passed `python3 -m scout pick` / `verify` in the same session.
- Persist memory by committing `data/history.json` (and profile edits) and pushing. `out/` and `.cache/` are scratch.
- Run tests with `python3 -m unittest tests.test_core` after changing anything in `scout/`.
