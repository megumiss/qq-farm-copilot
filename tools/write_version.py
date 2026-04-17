"""根据 Git tag 写入 utils/version.py。"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def _normalize_version(tag: str) -> str:
    text = str(tag or '').strip()
    if text[:1].lower() == 'v':
        text = text[1:].strip()
    if not text:
        return '0.0.0-dev'
    return text


def _normalize_tag(raw_tag: str) -> str:
    text = str(raw_tag or '').strip()
    if not text:
        return 'v0.0.0-dev'
    if text[:1].lower() != 'v':
        return f'v{text}'
    return text


def _sanitize_python_string(value: str) -> str:
    return re.sub(r"[\\']", lambda m: f'\\{m.group(0)}', str(value or ''))


def write_version_file(version_file: Path, version: str, repo: str) -> None:
    version = str(version or '').strip() or '0.0.0-dev'
    repo = str(repo or '').strip() or 'megumiss/qq-farm-copilot'
    content = (
        '"""应用版本信息。\n\n'
        '此文件可由 tools/write_version.py 在打包流程中自动更新。'
        '"""\n\n'
        f"APP_VERSION = '{_sanitize_python_string(version)}'\n"
        f"APP_GITHUB_REPO = '{_sanitize_python_string(repo)}'\n"
        "APP_RELEASES_URL = f'https://github.com/{APP_GITHUB_REPO}/releases/latest'\n"
    )
    version_file.parent.mkdir(parents=True, exist_ok=True)
    version_file.write_text(content, encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description='Write utils/version.py from tag.')
    parser.add_argument('--tag', default='', help='Release tag, e.g. v1.2.3')
    parser.add_argument('--repo', default='megumiss/qq-farm-copilot', help='GitHub repository slug')
    parser.add_argument('--output', default='utils/version.py', help='Output python file path')
    args = parser.parse_args()

    normalized_tag = _normalize_tag(args.tag)
    normalized_version = _normalize_version(normalized_tag)
    output_file = Path(args.output).resolve()
    write_version_file(output_file, normalized_version, args.repo)

    print(f'[write_version] tag={normalized_tag}')
    print(f'[write_version] version={normalized_version}')
    print(f'[write_version] output={output_file}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
