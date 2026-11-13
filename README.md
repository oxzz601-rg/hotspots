# hotspots

**Where should you refactor?** Not the file that annoys you most, and not the one with the worst lint score: the file that changes constantly *and* is hard to follow. That is where bugs cluster and where cleanup pays for itself.

`hotspots` reads your git history, measures churn and complexity per file, and ranks the intersection. One command, no service, no dependencies:

```bash
hotspots --since "1 year ago" --top 10
```

```markdown
# Refactor hotspots

318 commits by 7 contributor(s) in `.` since 1 year ago

| rank | file | score | commits | churn | complexity | risk | top author |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `src/billing.py` | 0.93 | 41 | 2,318 | 187 | hot and shared | Ada (38%) |
| 2 | `src/api/routes.py` | 0.78 | 33 | 1,204 | 142 | hot | Ada (61%) |
| 3 | `src/models.py` | 0.61 | 12 | 402 | 96 | spread thin | Sam (44%) |

## Files that change together

- `src/billing.py` + `src/api/routes.py` (14 commits)
```

Those numbers are illustrative; the shape is what matters. `billing.py` changes often, is branchy, and no single person owns it. `models.py` is calmer but nobody has the whole picture.

## Install

```bash
python -m pip install -e ".[dev]"
```

Python 3.9+ and `git` on your PATH. Nothing else.

## How the score works

```
churn        = lines added + lines deleted (from `git log --numstat`)
complexity   = branch keywords + 2 x definitions + average indent / 2 + 2 x log(lines)
score        = 0.6 x normalised log(churn) + 0.4 x normalised log(complexity)
```

Both inputs are log-scaled before normalising, because a file with 10,000 changed lines is not ten times more troubling than one with 1,000. Complexity is intentionally language-agnostic: counting `if`/`for`/`case`/`&&` and indentation works for Python, Go, TypeScript and shell alike, and needs no parser or virtualenv.

Risk labels add ownership:

- `hot and shared`: high score and three or more authors, the classic merge-conflict and regression magnet.
- `hot`: high score, one dominant author, so refactoring is likely unblocked.
- `spread thin`: no single owner, even if churn is moderate.

## Flags

| flag | meaning |
| --- | --- |
| `--since "1 year ago"` | any `git log --since` value; omit for the whole history |
| `--ext .py --ext .ts` | restrict to certain extensions (repeatable) |
| `--top 20` | how many files to show |
| `--json` | full report, including coupling and per-file authorship |
| `--html report.html` | self-contained browsable report |

## Use it in CI

```bash
hotspots --since "90 days ago" --json > hotspots.json
```

The JSON contains `files[].score`, `files[].risk` and `coupling`, so you can fail a pipeline when a new file crosses a threshold, or post the top five in a weekly summary.

## What this is not

- Not a linter or a type checker: it does not know whether your code is correct.
- Not cyclomatic complexity from an AST; that needs a parser per language. The proxy here is deliberately blunt but works everywhere.
- Not a productivity metric for people. Authorship is shown only to explain ownership risk, not to rank individuals.

Known blind spots: generated files and vendored directories appear until you exclude them with `--ext`; renames are followed with `--find-renames` but history before a rename may still be split; a very large monorepo benefits from `--ext` and `--since`.

## Tests

```bash
python -m pytest
```

The suite builds a temporary repository, makes commits from two authors, and checks ranking, churn, contributor counts, coupling, extension filters and both report formats.

MIT licensed.
