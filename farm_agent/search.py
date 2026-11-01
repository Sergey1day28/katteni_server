from pathlib import Path


class SearchResult:
    def __init__(self, path=None, error=None, names=None):
        self.path = path
        self.error = error
        self.names = list(names or [])


def _collect_files(root):
    files = []
    for item in root.iterdir():
        if item.is_file():
            files.append(item)
        elif item.is_dir():
            for child in item.iterdir():
                if child.is_file():
                    files.append(child)
    return files


def find_shortcut(root, email):
    root = Path(root)
    needle = (email or '').strip()
    if not needle:
        return SearchResult(error='не найден ярлык')
    matches = [path for path in _collect_files(root) if needle in path.name]
    if not matches:
        return SearchResult(error='не найден ярлык')
    if len(matches) > 1:
        return SearchResult(
            error='несколько ярлыков',
            names=[path.name for path in matches],
        )
    return SearchResult(path=matches[0])
