# Contributing to Robobench

Thanks for your interest. Robobench is an academic platform — we optimize
for clarity, reproducibility, and helping students/researchers get unstuck
fast. Contributions in any of these areas are welcome.

## Ways to contribute

- **New robot adapter**: implement `RobotAdapter` for a robot we don't yet
  support. See `docs/tutorials/adding-an-adapter.md` (Phase B).
- **Diagnostic panel**: add a panel to the dashboard that exposes a class
  of bring-up failure we don't yet detect.
- **Tutorial**: walk through a real debugging session you ran.
- **Bug report**: especially "the platform said X was healthy but actually
  Y was broken" — those are gold for us.

## Development setup

```bash
git clone https://github.com/logisticPM/robobench
cd robobench
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

## Code style

- Python: `ruff format` + `ruff check` (configured in `pyproject.toml`).
- Tests: pytest. Mock `subprocess`/SSH at the boundary — don't require a
  real robot in the unit test suite.
- Commit messages: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`,
  `ci:`, `test:`, `refactor:`). Keep the subject under 72 chars.

## Pull request checklist

- [ ] Tests added or updated
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `pytest` passes
- [ ] If you added a new public function/class, it has a one-line docstring
- [ ] CHANGELOG entry under `[Unreleased]` (CHANGELOG arrives in Phase B)

## Filing hardware-debug issues

Use the **Hardware issue** template (`.github/ISSUE_TEMPLATE/hardware_issue.md`).
Include: robot model, ROS distro, network topology, the exact command you ran,
and the platform's diagnostic output. Without those four, we can't reproduce.
