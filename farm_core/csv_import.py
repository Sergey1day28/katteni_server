import csv
import io
import logging
from pathlib import Path

from farm_core.models import Account, AccountLoginSecret, ImportReport


EMAIL_KEYS = frozenset({'email', 'account_email', 'почта', 'e-mail', 'e_mail'})
TOTP_KEYS = frozenset({'totp', 'totp_seed', 'ea_auth', 'auth', 'code_ea', 'k'})
NAME_KEYS = frozenset({'name', 'account_name', 'имя'})
EA_ID_KEYS = frozenset({'ea_account_id', 'account_id', 'ea_id'})
PASSWORD_KEYS = frozenset({'password', 'ea_password', 'pass', 'пароль'})
SHEET_EMAIL_COL = 0
SHEET_PASSWORD_COL = 6
SHEET_TOTP_COL = 10


def _sheet_mapping():
    return {
        'email': SHEET_EMAIL_COL,
        'password': SHEET_PASSWORD_COL,
        'totp': SHEET_TOTP_COL,
    }


def import_csv(csv_path=None, uploaded=None):
    if uploaded is not None:
        name = Path(getattr(uploaded, 'name', '') or 'upload.csv').name
        raw = uploaded.read()
        text = raw.decode('utf-8-sig') if isinstance(raw, (bytes, bytearray)) else raw
        rows = _rows_from_text(text or '')
        return _import_rows(rows, name)
    path = Path(csv_path)
    rows = _read_rows(path)
    return _import_rows(rows, str(path))


def _import_rows(rows, source_name):
    unresolved = []
    count = 0
    if not rows:
        return _report(source_name, {'accounts': 0}, unresolved)
    header_map = _header_map(rows[0])
    if 'email' in header_map:
        mapping = header_map
        data_rows = rows[1:]
        start_line = 2
    elif header_map:
        mapping = _sheet_mapping()
        data_rows = rows[1:]
        start_line = 2
    else:
        mapping = _sheet_mapping()
        data_rows = rows
        start_line = 1
    for offset, row in enumerate(data_rows):
        line = start_line + offset
        if _upsert_row(row, mapping, line, unresolved):
            count += 1
    return _report(source_name, {'accounts': count}, unresolved)


def _read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        return _rows_from_handle(handle)


def _rows_from_text(text):
    return _rows_from_handle(io.StringIO(text, newline=''))


def _rows_from_handle(handle):
    reader = csv.reader(handle)
    return [row for row in reader if any((cell or '').strip() for cell in row)]


def _norm_header(value):
    return (value or '').strip().lower().lstrip('\ufeff')


def _header_map(row):
    mapping = {}
    for index, cell in enumerate(row):
        key = _norm_header(cell)
        if key in EMAIL_KEYS:
            mapping['email'] = index
        elif key in TOTP_KEYS:
            mapping['totp'] = index
        elif key in NAME_KEYS:
            mapping['name'] = index
        elif key in EA_ID_KEYS:
            mapping['ea_id'] = index
        elif key in PASSWORD_KEYS:
            mapping['password'] = index
    return mapping


def _cell(row, index):
    if index is None or index < 0 or index >= len(row):
        return ''
    return (row[index] or '').strip()


def _parse_ea_id(value):
    text = (value or '').strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _looks_like_email(value):
    text = (value or '').strip()
    return bool(text) and text != 'None' and '@' in text


def _upsert_row(row, mapping, line, unresolved):
    email = _cell(row, mapping.get('email'))
    if not _looks_like_email(email):
        unresolved.append({'kind': 'account_no_email', 'line': line})
        return False
    totp = _cell(row, mapping.get('totp'))
    name = _cell(row, mapping.get('name'))
    ea_id = _parse_ea_id(_cell(row, mapping.get('ea_id')))
    by_id = Account.objects.filter(ea_account_id=ea_id).first() if ea_id is not None else None
    by_email = Account.objects.filter(email__iexact=email).first()
    if by_id and by_email and by_id.id != by_email.id:
        unresolved.append({
            'kind': 'account_id_email_conflict',
            'line': line,
            'email': email,
            'ea_account_id': ea_id,
        })
        return False
    if by_id:
        if by_id.email and by_id.email.lower() != email.lower():
            unresolved.append({
                'kind': 'account_id_email_conflict',
                'line': line,
                'email': email,
                'ea_account_id': ea_id,
            })
            return False
        account = by_id
        account.email = email
        if name:
            account.name = name
        account.save()
    elif by_email:
        if ea_id is not None and by_email.ea_account_id not in (None, ea_id):
            unresolved.append({
                'kind': 'account_id_email_conflict',
                'line': line,
                'email': email,
                'ea_account_id': ea_id,
            })
            return False
        account = by_email
        if ea_id is not None and account.ea_account_id is None:
            account.ea_account_id = ea_id
        if name:
            account.name = name
        account.save()
    else:
        account = Account.objects.create(
            email=email,
            name=name,
            ea_account_id=ea_id,
        )
    password = _cell(row, mapping.get('password'))
    defaults = {}
    if totp:
        defaults['totp_seed'] = totp
    if password:
        defaults['ea_password'] = password
    if defaults:
        AccountLoginSecret.objects.update_or_create(
            account=account,
            defaults=defaults,
        )
    logging.info('Импорт CSV: аккаунт %s', email)
    return True


def _report(source_name, summary, unresolved):
    return ImportReport.objects.create(
        source_path=str(source_name),
        summary=summary,
        unresolved=unresolved,
    )
