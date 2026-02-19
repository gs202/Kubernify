# Contributing to kubernify

Thank you for your interest in contributing to kubernify! This guide covers the development setup, coding standards, and process for submitting changes.

---

## Development Setup

kubernify uses [UV](https://docs.astral.sh/uv/) for dependency management and virtual environment handling.

### Prerequisites

- Python >= 3.10
- [UV](https://docs.astral.sh/uv/) installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Git

### Clone and Install

```bash
git clone https://github.com/gs202/Kubernify.git
cd kubernify
uv sync
uv run pre-commit install
```

This will:
1. Create a virtual environment
2. Install all runtime and dev dependencies from the lockfile
3. Set up pre-commit hooks for automated code quality checks

---

## Running Tests

```bash
uv run pytest
```

With coverage:

```bash
uv run pytest --cov=kubernify --cov-report=term-missing
```

---

## Code Quality Tools

### Linter

```bash
uv run ruff check src/ tests/
```

Auto-fix linting issues:

```bash
uv run ruff check --fix src/ tests/
```

### Formatter

```bash
uv run ruff format src/ tests/
```

Check formatting without modifying files:

```bash
uv run ruff format --check src/ tests/
```

### Type Checker

```bash
uv run mypy src/kubernify/
```

### Run All Checks

```bash
uv run pre-commit run --all-files
```

---

## Code Style

- **PEP 8** — All code must be PEP 8 compliant
- **Formatting** — [ruff](https://docs.astral.sh/ruff/) handles formatting (line length: 120)
- **Type hints** — Required on all function signatures (arguments and return types). Use modern Python 3.10+ syntax (`str | None` instead of `Optional[str]`)
- **Docstrings** — Required on all public modules, classes, and functions (Google style)
- **Imports** — Ordered by: standard library → third-party → internal. No wildcard imports

---

## Pull Request Process

1. **Fork** the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feature/my-feature
   ```

2. **Make your changes** — Write code, add tests, update documentation as needed

3. **Run all checks** before committing:
   ```bash
   uv run ruff check src/ tests/
   uv run ruff format src/ tests/
   uv run mypy src/kubernify/
   uv run pytest
   ```

4. **Commit** with a descriptive message (see [Commit Messages](#commit-messages))

5. **Push** your branch and open a Pull Request against `main`

6. **Address review feedback** — Maintainers may request changes before merging

### PR Requirements

- All CI checks must pass (lint, format, type check, tests)
- New features must include tests
- Breaking changes must be documented
- No internal or vendor-specific references in code or documentation

---

## Commit Messages

We recommend [Conventional Commits](https://www.conventionalcommits.org/) format:

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

**Types:**

| Type | Description |
|------|-------------|
| `feat` | A new feature |
| `fix` | A bug fix |
| `docs` | Documentation changes |
| `test` | Adding or updating tests |
| `refactor` | Code change that neither fixes a bug nor adds a feature |
| `chore` | Build process, dependency updates, tooling |
| `ci` | CI/CD configuration changes |

**Examples:**

```
feat(cli): add --include-cronjobs flag for CronJob verification
fix(stability): handle nil pod conditions in health check
docs: update CLI reference with new options
test(image-parser): add edge cases for multi-segment paths
```

---

## Reporting Issues

- **Bug reports** — Use the [bug report template](https://github.com/gs202/Kubernify/issues/new?template=bug_report.md)
- **Feature requests** — Use the [feature request template](https://github.com/gs202/Kubernify/issues/new?template=feature_request.md)

When reporting bugs, please include:
- kubernify version (`kubernify --version` or `python -c "import kubernify; print(kubernify.__version__)"`)
- Python version
- Kubernetes cluster version
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output

---

## License

By contributing to kubernify, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
