import re
from pathlib import Path


def user_data_dir(arguments):
    match = re.search(
        r'--user-data-dir=(?:"([^"]*)"|(\S+))',
        arguments or '',
        re.IGNORECASE,
    )
    if not match:
        return ''
    raw = match.group(1) if match.group(1) is not None else match.group(2)
    return raw.strip().rstrip('\\/')


def profile_directory(arguments):
    match = re.search(
        r'--profile-directory=(?:"([^"]*)"|(\S+))',
        arguments or '',
        re.IGNORECASE,
    )
    if not match:
        return ''
    raw = match.group(1) if match.group(1) is not None else match.group(2)
    return raw.strip()


def app_model_id(text, profile=''):
    match = re.search(r'Chrome\.UserData\.[A-Za-z0-9]+', text or '')
    if match:
        return match.group(0)
    name = (profile or '').replace(' ', '')
    if not name:
        return ''
    return 'Chrome.UserData.' + name


def read_lnk_text(path):
    data = Path(path).read_bytes()
    parts = []
    for match in re.finditer(b'(?:[\x20-\x7e]\x00){4,}', data):
        parts.append(match.group().decode('utf-16le'))
    return '\n'.join(parts)


def is_shared_chrome_dir(path):
    return Path(path or '').name.lower() == 'user data'


def command_matches(command_line, directory):
    needle = (directory or '').strip().lower().replace('/', '\\').rstrip('\\')
    if not needle:
        return False
    hay = (command_line or '').lower().replace('/', '\\')
    start = 0
    while True:
        index = hay.find(needle, start)
        if index < 0:
            return False
        end = index + len(needle)
        if end >= len(hay) or hay[end] in ' "\\':
            return True
        start = index + 1


def read_shortcut_arguments(path, run):
    escaped = str(path).replace("'", "''")
    script = "(New-Object -ComObject WScript.Shell).CreateShortcut('%s').Arguments" % escaped
    completed = run(
        ['powershell', '-NoProfile', '-Command', script],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or '').strip()
        raise OSError(completed.returncode, detail)
    return (completed.stdout or '').strip()
