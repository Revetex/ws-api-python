import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

INCLUDE_DIRS = [
    ROOT / 'wsapp_gui',
    ROOT,
]

EXCLUDE = {
    '.venv', 'venv', '__pycache__', 'build', 'dist', '.git',
}


def should_visit(p: Path) -> bool:
    parts = set(p.parts)
    return not parts.intersection(EXCLUDE)


def strip_file(path: Path) -> bool:
    try:
        original = path.read_text(encoding='utf-8')
    except Exception:
        return False
    lines = original.splitlines(keepends=True)
    changed = False
    new_lines = []
    for ln in lines:
        # Remove trailing whitespace but preserve newline
        if ln.endswith(('\n', '\r\n')):
            content = ln[:-1]
            newline = ln[-1]
            new_content = content.rstrip(' \t')
            if new_content != content:
                changed = True
            new_lines.append(new_content + newline)
        else:
            new_content = ln.rstrip(' \t')
            if new_content != ln:
                changed = True
            new_lines.append(new_content)
    if changed:
        path.write_text(''.join(new_lines), encoding='utf-8', newline='\n')
    return changed


def main():
    total = 0
    for base in INCLUDE_DIRS:
        for p in base.rglob('*.py'):
            if not should_visit(p):
                continue
            if strip_file(p):
                total += 1
    print(f"Stripped trailing whitespace in {total} files.")


if __name__ == '__main__':
    sys.exit(main())
