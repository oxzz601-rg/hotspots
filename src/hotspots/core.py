"""Churn x complexity analysis over a git history.

Churn alone flags files that change a lot. Complexity alone flags files that
are hard to read. Their intersection is where bugs cluster and where a refactor
earns its keep, so that is what gets ranked. Everything is offline and
dependency-free.
"""

from __future__ import annotations

import collections
import math
import pathlib
import re
import subprocess
from dataclasses import dataclass, field

BRANCH = re.compile(r"\b(if|elif|else|for|foreach|while|case|when|switch|catch|except|and|or|try)\b|[?]|&&|\|\|")
DEFINITION = re.compile(r"\b(def|function|func|fn|fun|class|struct|interface|sub)\b")
COMMIT_MARKER = "@@"
FIELD = "\x1f"
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".woff", ".woff2",
    ".ttf", ".eot", ".mp4", ".mp3", ".so", ".dll", ".dylib", ".exe", ".pyc", ".lock",
}


@dataclass
class FileStats:
    path: str
    commits: int = 0
    added: int = 0
    deleted: int = 0
    lines: int = 0
    branches: int = 0
    definitions: int = 0
    complexity: float = 0.0
    score: float = 0.0
    risk: str = ""
    authors: collections.Counter = field(default_factory=collections.Counter)

    @property
    def churn(self):
        return self.added + self.deleted

    @property
    def top_author(self):
        if not self.authors:
            return "", 0.0
        name, count = self.authors.most_common(1)[0]
        return name, count / max(1, self.commits)

    def to_dict(self):
        author, share = self.top_author
        return {
            "path": self.path,
            "commits": self.commits,
            "churn": self.churn,
            "added": self.added,
            "deleted": self.deleted,
            "lines": self.lines,
            "branches": self.branches,
            "definitions": self.definitions,
            "complexity": round(self.complexity, 2),
            "score": round(self.score, 3),
            "risk": self.risk,
            "authors": len(self.authors),
            "top_author": author,
            "top_author_share": round(share, 2),
        }


@dataclass
class Report:
    root: pathlib.Path
    since: str = None
    files: tuple = ()
    coupling: tuple = ()
    commits: int = 0
    contributors: int = 0
    skipped: int = 0

    def to_dict(self):
        return {
            "root": str(self.root),
            "since": self.since,
            "commits": self.commits,
            "contributors": self.contributors,
            "files": [item.to_dict() for item in self.files],
            "coupling": [
                {"first": first, "second": second, "commits": count} for first, second, count in self.coupling
            ],
        }


def _git(root, args):
    result = subprocess.run(["git", "-C", str(root)] + args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git failed; is this a repository?")
    return result.stdout


def _tracked_changes(root, since, extensions):
    args = ["log", "--numstat", "--date=short", "--find-renames", "--format={}%H{}%an".format(COMMIT_MARKER, FIELD)]
    if since:
        args.extend(["--since", since])
    output = _git(root, args)
    changes = []
    commit = author = None
    for line in output.splitlines():
        if line.startswith(COMMIT_MARKER):
            parts = line[len(COMMIT_MARKER) :].split(FIELD)
            commit = parts[0] if parts else None
            author = parts[1] if len(parts) > 1 else "unknown"
            continue
        if not line.strip() or commit is None:
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        added, deleted, path = fields[0], fields[1], fields[-1]
        path = path.replace('"', "")
        if " => " in path:
            path = path.split(" => ")[-1].strip("{} ")
        if extensions and not any(path.endswith(ext) for ext in extensions):
            continue
        changes.append(
            (
                commit,
                author,
                path,
                0 if added == "-" else int(added),
                0 if deleted == "-" else int(deleted),
            )
        )
    return changes


def complexity_of(text):
    """A deliberately simple, language-agnostic complexity proxy."""
    lines = [line for line in text.splitlines() if line.strip()]
    branches = len(BRANCH.findall(text))
    definitions = len(DEFINITION.findall(text))
    indents = [len(line) - len(line.lstrip(" \t")) for line in lines]
    average_indent = sum(indents) / len(indents) if indents else 0.0
    score = branches + definitions * 2 + average_indent / 2 + math.log1p(len(lines)) * 2
    return {
        "lines": len(lines),
        "branches": branches,
        "definitions": definitions,
        "average_indent": round(average_indent, 2),
        "score": round(score, 2),
    }


def analyze(root=".", since=None, extensions=None, max_files=800):
    root = pathlib.Path(root)
    try:
        _git(root, ["rev-parse", "--git-dir"])
    except RuntimeError as exc:
        raise RuntimeError("{} is not a git repository".format(root)) from exc
    try:
        _git(root, ["rev-parse", "--verify", "HEAD"])
    except RuntimeError:
        return Report(root=root, since=since)  # repository has no commits yet

    changes = _tracked_changes(root, since, extensions)
    if not changes:
        return Report(root=root, since=since)

    stats = {}
    per_commit = collections.defaultdict(set)
    commits = set()
    contributors = set()
    for commit, author, path, added, deleted in changes:
        commits.add(commit)
        contributors.add(author)
        per_commit[commit].add(path)
        entry = stats.setdefault(path, FileStats(path=path))
        entry.commits += 1
        entry.added += added
        entry.deleted += deleted
        entry.authors[author] += 1

    for path, entry in stats.items():
        if pathlib.Path(path).suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            if (root / path).stat().st_size > 2_000_000:
                continue
            text = (root / path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        metrics = complexity_of(text)
        entry.lines = metrics["lines"]
        entry.branches = metrics["branches"]
        entry.definitions = metrics["definitions"]
        entry.complexity = metrics["score"]

    ranked = sorted(stats.values(), key=lambda item: (-item.commits, -item.churn, item.path))[:max_files]
    max_churn = max((math.log1p(item.churn) for item in ranked), default=1.0) or 1.0
    max_complexity = max((math.log1p(item.complexity) for item in ranked), default=1.0) or 1.0
    for item in ranked:
        churn_part = math.log1p(item.churn) / max_churn
        complexity_part = math.log1p(item.complexity) / max_complexity
        item.score = round(0.6 * churn_part + 0.4 * complexity_part, 3)
        if item.score >= 0.6 and len(item.authors) >= 3:
            item.risk = "hot and shared"
        elif item.score >= 0.6:
            item.risk = "hot"
        elif len(item.authors) >= 4:
            item.risk = "spread thin"
    ranked.sort(key=lambda item: (-item.score, -item.churn, item.path))

    pairs = collections.Counter()
    for paths in per_commit.values():
        if not 2 <= len(paths) <= 25:
            continue
        ordered = sorted(paths)
        for first_index in range(len(ordered)):
            for second_index in range(first_index + 1, len(ordered)):
                pairs[(ordered[first_index], ordered[second_index])] += 1
    coupling = tuple((first, second, count) for (first, second), count in pairs.most_common(10) if count > 1)

    return Report(
        root=root,
        since=since,
        files=tuple(ranked),
        coupling=coupling,
        commits=len(commits),
        contributors=len(contributors),
        skipped=max(0, len(stats) - len(ranked)),
    )


def human_report(report, limit=20):
    lines = [
        "# Refactor hotspots",
        "",
        "{} commits by {} contributor(s) in `{}`{}".format(
            report.commits, report.contributors, report.root, " since {}".format(report.since) if report.since else ""
        ),
        "",
        "| rank | file | score | commits | churn | complexity | risk | top author |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rank, item in enumerate(report.files[:limit], start=1):
        author, share = item.top_author
        lines.append(
            "| {} | `{}` | {:.2f} | {} | {:,} | {:.0f} | {} | {} ({:.0%}) |".format(
                rank, item.path, item.score, item.commits, item.churn, item.complexity,
                item.risk or "-", author or "-", share,
            )
        )
    if report.coupling:
        lines += ["", "## Files that change together", ""]
        for first, second, count in report.coupling:
            lines.append("- `{}` + `{}` ({} commits)".format(first, second, count))
    lines += ["", "Score = 0.6 x normalised churn + 0.4 x normalised complexity, both log-scaled.", ""]
    return "\n".join(lines)


def render_html(report, limit=40):
    import html

    rows = []
    for rank, item in enumerate(report.files[:limit], start=1):
        rows.append(
            "<tr><td>{}</td><td><code>{}</code></td><td>{:.2f}</td><td>{}</td><td>{:,}</td><td>{:.0f}</td><td>{}</td></tr>".format(
                rank, html.escape(item.path), item.score, item.commits, item.churn,
                item.complexity, html.escape(item.risk or "-"),
            )
        )
    pairs = "".join(
        "<li><code>{}</code> + <code>{}</code> ({} commits)</li>".format(
            html.escape(first), html.escape(second), count
        )
        for first, second, count in report.coupling
    )
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Refactor hotspots</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;max-width:70rem;margin:2rem auto;padding:0 1rem;color:#1c1e21}}
code{{background:#f2f3f5;padding:.1rem .3rem;border-radius:3px}}
table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #e4e6eb;padding:.4rem .6rem;text-align:left}}
</style></head><body>
<h1>Refactor hotspots</h1>
<p>{commits} commits by {people} contributor(s) in <code>{root}</code>.</p>
<table><thead><tr><th>#</th><th>file</th><th>score</th><th>commits</th><th>churn</th><th>complexity</th><th>risk</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Files that change together</h2>
<ul>{pairs}</ul>
</body></html>
""".format(
        commits=report.commits,
        people=report.contributors,
        root=html.escape(str(report.root)),
        rows="\n".join(rows),
        pairs=pairs or "<li>none</li>",
    )
