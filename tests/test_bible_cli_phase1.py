from __future__ import annotations

from bible_cli.exceptions import COMMAND_NOT_IMPLEMENTED_EXIT_CODE
from bible_cli.python_cli import build_parser, main


def test_parser_exposes_phase1_command_tree() -> None:
    parser = build_parser()
    help_text = parser.format_help()

    assert "system" in help_text
    assert "knowledge" in help_text
    assert "memory" in help_text
    assert "skills" in help_text


def test_main_without_args_prints_help(capsys) -> None:
    exit_code = main([])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "usage: bs" in captured.out


def test_unimplemented_command_has_stable_exit_code(capsys) -> None:
    exit_code = main(["system", "health"])
    captured = capsys.readouterr()

    assert exit_code == COMMAND_NOT_IMPLEMENTED_EXIT_CODE
    assert "CLI_NOT_IMPLEMENTED" in captured.err
    assert "system health" in captured.err
