import json
import subprocess

import pytest

from hotspots.cli import main
from hotspots.core import analyze, complexity_of, human_report, render_html


@pytest.fixture()
def repo(tmp_path):
    def run(*args, author="Ada"):
        env = {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": "{}@example.com".format(author.lower()),
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": "{}@example.com".format(author.lower()),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }
        return subprocess.run(
            ["git", "-C", str(tmp_path)] + list(args), check=True, capture_output=True, text=True, env=env
        )

    run("init", "-q")
    run("config", "user.email", "ada@example.com")
    run("config", "user.name", "Ada")

    core = tmp_path / "core.py"
    helper = tmp_path / "helper.py"
    helper.write_text("def tiny(x):\n    return x\n")
    for index in range(4):
        core.write_text(
            "def process(value):\n"
            + "".join("    if value:\n        for item in value:\n            if item and item > {}:\n                value = value + 1\n".format(index) for _ in range(3))
            + "    return value\n"
        )
        run("add", "core.py", "helper.py")
        run("commit", "-q", "-m", "change {}".format(index), author="Ada" if index < 3 else "Bob")
    return tmp_path


def test_syntax_of_complexity_result():
    simple = complexity_of("x = 1\n")
    complex_code = complexity_of(
        "def f(a):\n    for i in a:\n        if i and i > 1:\n            while i:\n                i -= 1\n"
    )
    assert simple["branches"] == 0
    assert complex_code["branches"] >= 4
    assert complex_code["score"] > simple["score"]


def test_analysis_ranks_churn_and_complexity(repo):
    report = analyze(repo)
    assert report.commits == 4
    assert report.contributors == 2
    assert report.files[0].path == "core.py"
    top = report.files[0]
    assert top.commits == 4 and top.churn > 0
    assert top.score >= report.files[1].score
    assert top.authors["Ada"] == 3
    assert len(top.authors) == 2


def test_coupling_finds_files_committed_together(repo):
    report = analyze(repo)
    pairs = [(first, second) for first, second, _count in report.coupling]
    assert ("core.py", "helper.py") in pairs


def test_extension_filter(repo):
    assert analyze(repo, extensions=(".md",)).files == ()
    assert analyze(repo, extensions=(".py",)).files


def test_unreadable_or_empty_repository(tmp_path):
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    empty = analyze(tmp_path)
    assert empty.files == () and empty.commits == 0
    with pytest.raises(RuntimeError):
        analyze(tmp_path / "missing")


def test_reports_are_rendered(repo):
    report = analyze(repo)
    table = human_report(report)
    assert "Refactor hotspots" in table
    assert "core.py" in table
    page = render_html(report)
    assert "<table>" in page and "core.py" in page
    assert json.dumps(report.to_dict())[:1] == "{"


def test_cli_json_and_markdown(repo, capsys):
    assert main([str(repo), "--json", "--top", "1"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["files"]) == 1
    assert payload["files"][0]["path"] == "core.py"
    assert main([str(repo)]) == 0
    assert "| rank | file |" in capsys.readouterr().out
    assert main([str(repo / "nope")]) == 2
