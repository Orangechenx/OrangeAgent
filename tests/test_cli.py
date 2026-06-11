import pytest
from typer.testing import CliRunner
from unittest.mock import patch, AsyncMock

from orangeagent.cli.app import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "run" in result.stdout
    assert "log" in result.stdout
    assert "send" in result.stdout
    assert "tasks" in result.stdout
    assert "runs" in result.stdout
    assert "memory" in result.stdout
    assert "evidence" in result.stdout
    assert "tools" in result.stdout
    assert "handoffs" in result.stdout
    assert "steps" in result.stdout
    assert "cleanup" in result.stdout
    assert "eval" in result.stdout


def test_cli_run_help():
    result = runner.invoke(app, ["run", "--help"])
    assert result.exit_code == 0
    assert "TUI" in result.stdout or "交互" in result.stdout


def test_cli_log_help():
    result = runner.invoke(app, ["log", "--help"])
    assert result.exit_code == 0
    assert "--from" in result.stdout
    assert "--limit" in result.stdout
    assert "--type" in result.stdout


def test_cli_send_help():
    result = runner.invoke(app, ["send", "--help"])
    assert result.exit_code == 0
    assert "--transport" in result.stdout
    assert "--server-url" in result.stdout


@patch("orangeagent.cli.app._show_log", new_callable=AsyncMock)
def test_cli_log_invokes_show_log(mock_show_log):
    result = runner.invoke(app, ["log"])
    assert result.exit_code == 0


@patch("orangeagent.cli.app._send_message", new_callable=AsyncMock)
def test_cli_send_invokes_send_message(mock_send):
    result = runner.invoke(app, ["send", "hello agent"])
    assert result.exit_code == 0
    mock_send.assert_awaited_once_with("hello agent", "local", None)


@patch("orangeagent.cli.app._show_tasks", new_callable=AsyncMock)
def test_cli_tasks_invokes_show_tasks(mock_show_tasks):
    result = runner.invoke(app, ["tasks", "--session-id", "s1"])
    assert result.exit_code == 0
    mock_show_tasks.assert_awaited_once_with("s1", 50, "local", None)


@patch("orangeagent.cli.app._show_runs", new_callable=AsyncMock)
def test_cli_runs_invokes_show_runs(mock_show_runs):
    result = runner.invoke(app, ["runs", "--run-id", "r1"])
    assert result.exit_code == 0
    mock_show_runs.assert_awaited_once_with(None, "r1", 50, "local", None)


@patch("orangeagent.cli.app._show_memory", new_callable=AsyncMock)
def test_cli_memory_invokes_show_memory(mock_show_memory):
    result = runner.invoke(app, ["memory", "--task-id", "t1"])
    assert result.exit_code == 0
    mock_show_memory.assert_awaited_once_with(None, "t1", 50, "local", None)


@patch("orangeagent.cli.app._show_evidence", new_callable=AsyncMock)
def test_cli_evidence_invokes_show_evidence(mock_show_evidence):
    result = runner.invoke(app, ["evidence", "--task-id", "t1"])
    assert result.exit_code == 0
    mock_show_evidence.assert_awaited_once_with("t1", 50, "local", None)


@patch("orangeagent.cli.app._show_tools", new_callable=AsyncMock)
def test_cli_tools_invokes_show_tools(mock_show_tools):
    result = runner.invoke(app, ["tools", "--task-id", "t1"])
    assert result.exit_code == 0
    mock_show_tools.assert_awaited_once_with("t1", 50, "local", None)


@patch("orangeagent.cli.app._show_handoffs", new_callable=AsyncMock)
def test_cli_handoffs_invokes_show_handoffs(mock_show_handoffs):
    result = runner.invoke(app, ["handoffs", "--task-id", "t1"])
    assert result.exit_code == 0
    mock_show_handoffs.assert_awaited_once_with("t1", None, 50, "local", None)


@patch("orangeagent.cli.app._show_steps", new_callable=AsyncMock)
def test_cli_steps_invokes_show_steps(mock_show_steps):
    result = runner.invoke(app, ["steps", "--run-id", "r1"])
    assert result.exit_code == 0
    mock_show_steps.assert_awaited_once_with(None, "r1", 100, "local", None)


@patch("orangeagent.cli.app._cleanup_runtime", new_callable=AsyncMock)
def test_cli_cleanup_invokes_runtime_cleanup(mock_cleanup):
    result = runner.invoke(app, ["cleanup", "--max-memories-per-task", "2"])
    assert result.exit_code == 0
    mock_cleanup.assert_awaited_once_with(2, "local", None)


@patch("orangeagent.cli.app._run_eval", new_callable=AsyncMock)
def test_cli_eval_invokes_runtime_eval(mock_eval):
    result = runner.invoke(app, ["eval"])
    assert result.exit_code == 0
    mock_eval.assert_awaited_once_with("local", None)
