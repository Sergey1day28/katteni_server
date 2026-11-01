import os
import sys
from pathlib import Path

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farm_site.settings')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import django

django.setup()

from farm_core.csv_import import import_csv
from farm_core.legacy_import import import_legacy


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.stderr.write('Укажите путь к db.sqlite3 или CSV\n')
        return 1
    source = args[0]
    if str(source).lower().endswith('.csv'):
        report = import_csv(source)
    else:
        report = import_legacy(source)
    sys.stdout.write('Импорт %s: %s\n' % (report.id, report.summary))
    if report.unresolved:
        sys.stdout.write('Спорные строки: %s\n' % len(report.unresolved))
        for item in report.unresolved:
            sys.stdout.write('%s\n' % item)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
