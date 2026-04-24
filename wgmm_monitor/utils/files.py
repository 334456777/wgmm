"""文件处理工具."""

from __future__ import annotations

from pathlib import Path


def limit_file_lines(filepath: Path, max_lines: int, header_lines: int = 0) -> None:
	"""限制文本文件最大行数, 可保留文件头部若干行."""
	if not filepath.exists():
		return

	lines = filepath.read_text(encoding="utf-8").splitlines(keepends=True)
	if len(lines) <= max_lines:
		return

	if header_lines > 0:
		keep_lines = lines[:header_lines] + lines[-(max_lines - header_lines) :]
	else:
		keep_lines = lines[-max_lines:]
	filepath.write_text("".join(keep_lines), encoding="utf-8")
