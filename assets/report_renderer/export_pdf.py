from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote


PDF_SUFFIX = ".pdf"
DIAGNOSTIC_TAIL_LINES = 12


def find_browsers() -> list[Path]:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    ]
    browsers: list[Path] = []
    for candidate in candidates:
        if candidate.exists():
            browsers.append(candidate)

    for name in ("chrome", "chrome.exe", "msedge", "msedge.exe", "chromium", "chromium.exe"):
        found = shutil.which(name)
        if found and Path(found) not in browsers:
            browsers.append(Path(found))
    return browsers


def find_browser() -> Path | None:
    browsers = find_browsers()
    return browsers[0] if browsers else None


def manual_instruction_path(pdf_path: Path) -> Path:
    return pdf_path.with_name(f"{pdf_path.stem}_pdf_export_instructions.md")


def manual_export_instructions(html_path: Path, pdf_path: Path) -> str:
    return f"""# PDF 手动导出说明

自动 PDF 导出未成功，可以按下面方式手动生成：

1. 用 Chrome / Edge 打开：
   `{html_path.resolve()}`
2. 按 `Ctrl + P`。
3. 目标选择“另存为 PDF”。
4. 关闭“页眉和页脚”，避免出现浏览器路径、日期和页码。
5. 开启“背景图形”，保证卡片底色和排版效果正常显示。
6. 纸张选择 A4，边距可选择“默认”或“无”以外的安全边距。
7. 保存为：
   `{pdf_path.resolve()}`
"""


def write_manual_instructions(html_path: Path, pdf_path: Path, output_path: Path | None = None) -> Path:
    target = output_path or manual_instruction_path(pdf_path)
    target.write_text(manual_export_instructions(html_path, pdf_path), encoding="utf-8")
    return target


class _QuietRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def local_http_server(directory: Path):
    """Expose one report directory to a loopback-only temporary HTTP server."""
    handler = partial(_QuietRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _tail(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    lines = [line for line in (value or "").strip().splitlines() if line.strip()]
    return "\n".join(lines[-DIAGNOSTIC_TAIL_LINES:]) or "（无输出）"


def _diagnostic(
    browser: Path,
    headless_flag: str,
    source_kind: str,
    *,
    return_code: int | None = None,
    stderr: str | bytes | None = None,
    stdout: str | bytes | None = None,
    timed_out: bool = False,
    error: str = "",
) -> str:
    details = [
        f"模式={source_kind}",
        f"浏览器={browser}",
        f"headless参数={headless_flag}",
        f"超时={'是' if timed_out else '否'}",
    ]
    if return_code is not None:
        details.append(f"返回码={return_code}")
    if error:
        details.append(f"错误={error}")
    details.append(f"stderr末尾：{_tail(stderr)}")
    details.append(f"stdout末尾：{_tail(stdout)}")
    return "；".join(details)


def run_browser_attempt(
    browser: Path,
    headless_flag: str,
    pdf_path: Path,
    source_url: str,
    source_kind: str,
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory(prefix="report-renderer-pdf-", ignore_cleanup_errors=True) as profile_dir:
        command = [
            str(browser),
            headless_flag,
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--disable-sync",
            "--disable-dev-shm-usage",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            "--no-pdf-header-footer",
            "--print-to-pdf-no-header",
            f"--user-data-dir={profile_dir}",
            f"--print-to-pdf={pdf_path}",
            source_url,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=90,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return False, _diagnostic(
                browser,
                headless_flag,
                source_kind,
                stderr=exc.stderr,
                stdout=exc.stdout,
                timed_out=True,
                error="浏览器导出超时（90 秒）",
            )
        except OSError as exc:
            return False, _diagnostic(browser, headless_flag, source_kind, error=str(exc))

    if result.returncode == 0 and pdf_path.exists() and pdf_path.stat().st_size > 0:
        return True, _diagnostic(
            browser,
            headless_flag,
            source_kind,
            return_code=result.returncode,
            stderr=result.stderr,
            stdout=result.stdout,
        )
    reason = "浏览器未生成有效 PDF 文件" if result.returncode == 0 else "浏览器命令失败"
    return False, _diagnostic(
        browser,
        headless_flag,
        source_kind,
        return_code=result.returncode,
        stderr=result.stderr,
        stdout=result.stdout,
        error=reason,
    )


def _export_from_url(html_path: Path, pdf_path: Path, source_url: str, source_kind: str) -> tuple[bool, list[str]]:
    diagnostics: list[str] = []
    for browser in find_browsers():
        for headless_flag in ("--headless=new", "--headless"):
            ok, detail = run_browser_attempt(browser, headless_flag, pdf_path, source_url, source_kind)
            diagnostics.append(detail)
            if ok:
                return True, diagnostics
    return False, diagnostics


def export_pdf(html_path: Path, pdf_path: Path) -> tuple[bool, str]:
    html_path = html_path.resolve()
    pdf_path = pdf_path.resolve()

    if not html_path.exists():
        return False, f"找不到 HTML 文件：{html_path}"
    if not find_browsers():
        return False, "未检测到可用的 Chrome / Edge，已切换为手动导出说明。"

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    file_ok, diagnostics = _export_from_url(html_path, pdf_path, html_path.as_uri(), "file://")
    if file_ok:
        return True, f"PDF 已生成（file://）：{pdf_path}\n{diagnostics[-1]}"

    with local_http_server(html_path.parent) as base_url:
        local_url = f"{base_url}/{quote(html_path.name)}"
        local_ok, local_diagnostics = _export_from_url(html_path, pdf_path, local_url, "localhost")
    diagnostics.extend(local_diagnostics)
    if local_ok:
        return True, f"PDF 已生成（localhost 回退）：{pdf_path}\n{diagnostics[-1]}"

    diagnostic_text = "\n".join(diagnostics)
    return False, f"自动 PDF 导出失败，已尝试 file:// 和 localhost 回退。\n{diagnostic_text}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a local report HTML file to a same-name PDF.")
    parser.add_argument("--html", required=True, help="Path to a report HTML file")
    parser.add_argument("--pdf", help="PDF path. Defaults to the same name as HTML, with a .pdf suffix.")
    args = parser.parse_args()

    html_path = Path(args.html)
    pdf_path = Path(args.pdf) if args.pdf else html_path.with_suffix(PDF_SUFFIX)
    ok, message = export_pdf(html_path, pdf_path)
    print(message)
    if not ok:
        instructions = write_manual_instructions(html_path, pdf_path)
        print(f"已生成手动导出说明：{instructions}")


if __name__ == "__main__":
    main()
