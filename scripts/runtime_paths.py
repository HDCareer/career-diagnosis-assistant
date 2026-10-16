#!/usr/bin/env python3
"""Resolve SkillⅠ runtime paths without creating directories or reading Case data.

The same file is used from the development repository and from the installed
Plugin. Runtime detection is filesystem based; Plugin mode never requires Git
or a development repository.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


CORE_RELATIVE_PATH = Path("02-回国求职Skill") / "回国求职竞争力分析与岗位方向指引Skill"
PLUGIN_NAME = "skill1-career-diagnosis"
WORKFLOW_SCRIPT_NAMES = (
    "case_state.py",
    "consultation_truth.py",
    "content_contract.py",
    "content_materializer.py",
    "quality_gate.py",
    "workflow_orchestrator.py",
    "renderer_adapter.py",
)


class RuntimePathError(Exception):
    """Raised when neither supported runtime layout is complete."""


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _nearest_git_root(path: Path) -> Path | None:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _user_data_root() -> Path:
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_app_data:
            return Path(local_app_data).expanduser().resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support").resolve()
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser().resolve()
    return (Path.home() / ".local" / "share").resolve()


def _is_temp_path(path: Path) -> bool:
    temp_root = Path(tempfile.gettempdir()).resolve()
    return _is_relative_to(path, temp_root)


@dataclass(frozen=True)
class RuntimePaths:
    mode: str
    runtime_root: Path
    skill_root: Path
    core_root: Path
    workflow_root: Path
    workflow_references_root: Path | None
    renderer_root: Path
    entry_skill: Path
    plugin_runtime_contract: Path | None

    def core_skill_file(self) -> Path:
        """Return the business-core file for the active runtime mode."""
        if self.mode == "plugin":
            return self.core_root / "skill1_core.md"
        return self.core_root / "SKILL.md"

    def script_file(self, name: str) -> Path:
        """Return a workflow script path for the active runtime mode."""
        if name not in WORKFLOW_SCRIPT_NAMES:
            raise RuntimePathError(f"Unsupported workflow script: {name}")
        return self.workflow_root / name

    def script_files(self) -> dict[str, Path]:
        """Return all supported workflow script paths for the active runtime mode."""
        return {name: self.script_file(name) for name in WORKFLOW_SCRIPT_NAMES}

    def renderer_entry(self) -> Path:
        """Return the Renderer entry file for the active runtime mode."""
        return self.renderer_root / "render_report.py"

    def executable_paths(self) -> dict[str, str]:
        """Return the mode-specific executable path matrix for audits and tests."""
        data = {name: str(path) for name, path in self.script_files().items()}
        data["render_report.py"] = str(self.renderer_entry())
        return data

    def default_case_root(self, explicit_root: str | None = None) -> Path:
        """Return a path only; callers decide whether an operation may create it."""
        if explicit_root:
            root = Path(explicit_root).expanduser().resolve()
            return self.ensure_case_root_allowed(root)
        overridden = os.environ.get("SKILL1_CASE_ROOT") or os.environ.get("SKILL1_CASES_ROOT")
        if overridden:
            return self.ensure_case_root_allowed(Path(overridden).expanduser().resolve())
        return self.ensure_case_root_allowed((_user_data_root() / "Skill1-Cases").resolve())

    def ensure_case_root_allowed(self, root: Path) -> Path:
        """Reject production Case roots inside a Git repository or Plugin package."""
        resolved = root.expanduser().resolve()
        test_mode = _truthy_env("SKILL1_CASE_TEST_MODE")
        if test_mode:
            if not _is_temp_path(resolved):
                raise RuntimePathError("测试模式下 Case 根目录只能使用系统临时目录。")
            return resolved
        if self.mode == "repository" and _is_relative_to(resolved, self.runtime_root):
            raise RuntimePathError("生产模式拒绝在当前 Git 仓库内创建或使用 Case 根目录；请使用仓库外路径或设置 SKILL1_CASE_ROOT。")
        if self.mode == "plugin" and _is_relative_to(resolved, self.runtime_root):
            raise RuntimePathError("生产模式拒绝在 Plugin 安装目录内创建或使用 Case 根目录；请使用外部用户数据目录。")
        git_root = _nearest_git_root(resolved)
        if git_root is not None:
            raise RuntimePathError("生产模式拒绝在任意 Git 仓库内创建或使用 Case 根目录；请使用仓库外路径。")
        return resolved

    def technical_paths(self) -> dict[str, str | None]:
        return {
            "mode": self.mode,
            "runtime_root": str(self.runtime_root),
            "skill_root": str(self.skill_root),
            "core_root": str(self.core_root),
            "workflow_root": str(self.workflow_root),
            "workflow_references_root": str(self.workflow_references_root) if self.workflow_references_root else None,
            "renderer_root": str(self.renderer_root),
            "entry_skill": str(self.entry_skill),
            "core_skill_file": str(self.core_skill_file()),
            "plugin_runtime_contract": str(self.plugin_runtime_contract) if self.plugin_runtime_contract else None,
            "default_case_root": str(self.default_case_root()),
            "executables": self.executable_paths(),
        }


def _repository_paths(script_dir: Path) -> RuntimePaths | None:
    repo_root = script_dir.parent
    baseline = repo_root / "docs" / "maintenance" / "skill1-production-baseline.md"
    renderer_root = repo_root / "report_renderer"
    entry_skill = repo_root / ".agents" / "skills" / PLUGIN_NAME / "SKILL.md"
    core_root = repo_root / CORE_RELATIVE_PATH
    if script_dir.name != "workflow" or not (baseline.is_file() and (renderer_root / "render_report.py").is_file() and entry_skill.is_file() and (core_root / "SKILL.md").is_file()):
        return None
    return RuntimePaths(
        mode="repository",
        runtime_root=repo_root,
        skill_root=entry_skill.parent,
        core_root=core_root,
        workflow_root=script_dir,
        workflow_references_root=None,
        renderer_root=renderer_root,
        entry_skill=entry_skill,
        plugin_runtime_contract=None,
    )


def _plugin_paths(script_dir: Path) -> RuntimePaths | None:
    skill_root = script_dir.parent
    core_root = skill_root / "references" / "core"
    renderer_root = skill_root / "assets" / "report_renderer"
    contract = skill_root / "references" / "plugin_runtime_contract.md"
    workflow_references = skill_root / "references" / "workflow"
    entry_skill = skill_root / "SKILL.md"
    if script_dir.name != "scripts" or not ((core_root / "skill1_core.md").is_file() and (renderer_root / "render_report.py").is_file() and contract.is_file() and entry_skill.is_file()):
        return None
    return RuntimePaths(
        mode="plugin",
        runtime_root=skill_root,
        skill_root=skill_root,
        core_root=core_root,
        workflow_root=script_dir,
        workflow_references_root=workflow_references,
        renderer_root=renderer_root,
        entry_skill=entry_skill,
        plugin_runtime_contract=contract,
    )


def resolve_runtime(script_file: str | Path | None = None) -> RuntimePaths:
    """Prefer the self-contained Plugin layout, then fall back to repository mode."""
    script_dir = Path(script_file or __file__).resolve().parent
    plugin = _plugin_paths(script_dir)
    if plugin:
        return plugin
    repository = _repository_paths(script_dir)
    if repository:
        return repository
    raise RuntimePathError("未找到完整的 SkillⅠ repository 或 Plugin 运行结构。")


def cmd_show(args: argparse.Namespace) -> None:
    paths = resolve_runtime()
    data = paths.technical_paths()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    for key, value in data.items():
        print(f"{key}: {value}")


def cmd_self_check(_: argparse.Namespace) -> None:
    paths = resolve_runtime()
    required = [paths.entry_skill, paths.core_skill_file(), paths.renderer_entry(), *paths.script_files().values()]
    if paths.mode == "repository":
        required.append(paths.runtime_root / "docs" / "maintenance" / "skill1-production-baseline.md")
    else:
        required.extend([paths.plugin_runtime_contract, paths.workflow_references_root])
    if any(path is None or not path.exists() for path in required):
        raise RuntimePathError("当前运行模式缺少必需文件。")
    print(f"self-check 通过：识别为 {paths.mode} 模式；未创建 Case 目录，未调用 Renderer。")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Resolve portable SkillⅠ runtime paths without creating Case directories.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("self-check", help="静态检查当前运行模式。")
    check.set_defaults(handler=cmd_self_check)
    show = subparsers.add_parser("show", help="显示技术路径，不创建目录。")
    show.add_argument("--json", action="store_true")
    show.set_defaults(handler=cmd_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
        return 0
    except RuntimePathError as exc:
        print(f"运行路径解析已停止：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
