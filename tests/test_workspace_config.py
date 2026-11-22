"""Regression checks for the local VS Code launch configuration."""
import configparser
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = r"${env:SystemRoot}\System32\WindowsPowerShell\v1.0\powershell.exe"


def test_launcher_tasks_bypass_the_integrated_shell():
    tasks = json.loads((ROOT / ".vscode" / "tasks.json").read_text(encoding="utf-8"))
    launchers = {
        task["label"]: task
        for task in tasks["tasks"]
        if task["label"].startswith("OKai: ")
    }

    for label in (
        "OKai: Run dashboard",
        "OKai: Setup only",
        "OKai: Rebuild data and model",
    ):
        task = launchers[label]
        assert task["type"] == "process"
        assert task["command"] == POWERSHELL
        file_index = task["args"].index("-File")
        assert task["args"][file_index + 1] == r"${workspaceFolder}\run.ps1"
        assert task["options"]["cwd"] == "${workspaceFolder}"


def test_pytest_uses_a_project_local_temp_directory():
    config = configparser.ConfigParser()
    config.read(ROOT / "pytest.ini", encoding="utf-8")

    assert config["pytest"]["addopts"] == "--basetemp=.pytest-tmp"


def test_windows_launcher_recovers_stale_copied_environments():
    launcher = (ROOT / "run.ps1").read_text(encoding="utf-8")

    assert "$pythonWorks" in launcher
    assert "$pythonHome" in launcher
    assert "& $python --version" in launcher
    assert "$venvArguments += '--clear'" in launcher


def test_windows_console_fallback_uses_the_repository_launcher():
    launcher = (ROOT / "run.cmd").read_text(encoding="utf-8")

    assert 'set "REPO_ROOT=%~dp0"' in launcher
    assert '"%REPO_ROOT%run.ps1" %*' in launcher
