from farm_core.mode_labels import MODE_TITLES, normalize_mode_item, normalize_modes

KEY_TITLES = {key: title for title, key in MODE_TITLES.items()}

SESSION_ITEMS = (
    {'key': 'firstLoginToWeb', 'title': KEY_TITLES['firstLoginToWeb']},
    {'key': 'checkBanOnLogin', 'title': KEY_TITLES['checkBanOnLogin']},
    {
        'key': 'requests24hours',
        'title': KEY_TITLES['requests24hours'],
        'needs_value': True,
    },
    {
        'key': 'closeIfRequestAllowedExceeded',
        'title': KEY_TITLES['closeIfRequestAllowedExceeded'],
    },
    {
        'key': 'reloadPageIfFullTransferList',
        'title': KEY_TITLES['reloadPageIfFullTransferList'],
    },
    {'key': 'freeAccountSolving', 'title': KEY_TITLES['freeAccountSolving']},
)

SESSION_PREFIX = (
    'firstLoginToWeb',
    'checkBanOnLogin',
)

SESSION_SUFFIX = (
    'requests24hours',
    'closeIfRequestAllowedExceeded',
    'reloadPageIfFullTransferList',
    'freeAccountSolving',
)

ACTION_CARDS = (
    {
        'key': 'checkMarketOpened',
        'title': KEY_TITLES['checkMarketOpened'],
        'conditions': (),
    },
    {
        'key': 'collectObjectives',
        'title': KEY_TITLES['collectObjectives'],
        'conditions': (),
    },
    {
        'key': 'collectSBC',
        'title': KEY_TITLES['collectSBC'],
        'scope': True,
        'conditions': (
            {
                'key': 'priorityFailsCollectAll',
                'title': KEY_TITLES['priorityFailsCollectAll'],
            },
            {
                'key': 'solveIf100duplicate',
                'title': KEY_TITLES['solveIf100duplicate'],
            },
            {
                'key': 'doNotTakePlayerFromSquadToSbc',
                'title': KEY_TITLES['doNotTakePlayerFromSquadToSbc'],
            },
            {
                'key': 'useBronze200ForSbc',
                'title': KEY_TITLES['useBronze200ForSbc'],
            },
            {
                'key': 'collectSBCnotPriorityMax',
                'title': KEY_TITLES['collectSBCnotPriorityMax'],
                'needs_value': True,
            },
            {
                'key': 'sbcOnlyClubStorage',
                'title': KEY_TITLES['sbcOnlyClubStorage'],
            },
        ),
    },
    {
        'key': 'openPacks',
        'title': KEY_TITLES['openPacks'],
        'conditions': (
            {'key': 'openTradablePacks', 'title': KEY_TITLES['openTradablePacks']},
            {'key': 'openUnTradablePacks', 'title': KEY_TITLES['openUnTradablePacks']},
            {'key': 'open10coinsPacks', 'title': KEY_TITLES['open10coinsPacks']},
            {
                'key': 'openUntradeablePackAfterOneRound',
                'title': KEY_TITLES['openUntradeablePackAfterOneRound'],
            },
            {
                'key': 'doNotOpenPackInPlEx',
                'title': KEY_TITLES['doNotOpenPackInPlEx'],
                'needs_value': True,
            },
            {
                'key': 'openBronzePacksFromStore',
                'title': KEY_TITLES['openBronzePacksFromStore'],
                'needs_value': True,
            },
        ),
    },
    {
        'key': 'openPreviewPack',
        'title': KEY_TITLES['openPreviewPack'],
        'conditions': (),
    },
    {
        'key': 'handleUnsigned',
        'title': KEY_TITLES['handleUnsigned'],
        'conditions': (),
    },
    {
        'key': 'sellPlayers',
        'title': KEY_TITLES['sellPlayers'],
        'conditions': (
            {
                'key': 'quickSellIfNotSell',
                'title': KEY_TITLES['quickSellIfNotSell'],
                'needs_value': True,
            },
            {
                'key': 'quickSellIfMinNotSold',
                'title': KEY_TITLES['quickSellIfMinNotSold'],
            },
            {
                'key': 'quickSellSilverBronzeDublicat',
                'title': KEY_TITLES['quickSellSilverBronzeDublicat'],
            },
            {
                'key': 'quickSellRatingBelowAndEqual',
                'title': KEY_TITLES['quickSellRatingBelowAndEqual'],
                'needs_value': True,
            },
            {
                'key': 'quickSellRareGoldLowPricePlayers',
                'title': KEY_TITLES['quickSellRareGoldLowPricePlayers'],
            },
            {
                'key': 'quickSellLoanFromClub',
                'title': KEY_TITLES['quickSellLoanFromClub'],
            },
        ),
    },
    {
        'key': 'checkTransferList',
        'title': KEY_TITLES['checkTransferList'],
        'conditions': (
            {'key': 'relistAll', 'title': KEY_TITLES['relistAll']},
        ),
    },
    {
        'key': 'startSnipe',
        'title': KEY_TITLES['startSnipe'],
        'needs_value': True,
        'conditions': (
            {
                'key': 'resetRequests',
                'title': KEY_TITLES['resetRequests'],
                'needs_value': True,
            },
        ),
    },
)

SCOPE_KEYS = {
    'all': 'collectAllSbc',
    'priority': 'collectPrioritySbc',
    'notPriority': 'collectNotPrioritySbc',
}

SCOPE_BY_KEY = {value: name for name, value in SCOPE_KEYS.items()}

QUEUE_ORDER = tuple(card['key'] for card in ACTION_CARDS)

QUEUE_INDEX = {key: index for index, key in enumerate(QUEUE_ORDER)}

ACTION_BY_KEY = {card['key']: card for card in ACTION_CARDS}

SESSION_BY_KEY = {item['key']: item for item in SESSION_ITEMS}

SESSION_KEY_SET = frozenset(SESSION_BY_KEY)


def _condition_owner():
    owner = {}
    for card in ACTION_CARDS:
        for cond in card['conditions']:
            owner[cond['key']] = card['key']
    for scope_key in SCOPE_KEYS.values():
        owner[scope_key] = 'collectSBC'
    return owner


CONDITION_OWNER = _condition_owner()

BRONZE_PACK_KEY = 'openBronzePacksFromStore'


def default_folder_modes():
    return [{'key': 'freeAccountSolving', 'value': None}]


def _post_on(post, key):
    return bool(post.get('mode_%s' % key))


def _post_value(post, key):
    raw = (post.get('mode_value_%s' % key) or '').strip()
    if raw == '':
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _field_key(slot, key):
    if slot is None:
        return key
    return '%s_%s' % (slot, key)


def _append(items, key, value=None, slot=None):
    row = {'key': key, 'value': value}
    if slot is not None:
        row['slot'] = int(slot)
    items.append(row)


def _posted_scope_name(post, slot):
    if slot is None:
        raw = post.get('sbc_scope')
    else:
        raw = post.get('sbc_scope_%s' % slot)
    if raw in SCOPE_KEYS:
        return raw
    return None


def _emit_session(items, keys, post):
    for key in keys:
        spec = SESSION_BY_KEY[key]
        if not _post_on(post, key):
            continue
        value = _post_value(post, key) if spec.get('needs_value') else None
        _append(items, key, value)


def _checked_cards(post):
    slots = _posted_slots(post)
    chosen = []
    if slots:
        for slot in slots:
            key = (post.get('queue_key_%s' % slot) or '').strip()
            if key in ACTION_BY_KEY and _post_on(post, _field_key(slot, key)):
                chosen.append((slot, key))
        return chosen
    for key in QUEUE_ORDER:
        if _post_on(post, key):
            chosen.append((None, key))
    return chosen


def _shared_profile(post, spec, slots):
    conditions = {}
    scope_name = 'all'
    action_value = None
    for slot in slots:
        if spec.get('needs_value'):
            posted = _post_value(post, _field_key(slot, spec['key']))
            if posted is not None:
                action_value = posted
        chosen_scope = _posted_scope_name(post, slot)
        if spec.get('scope') and chosen_scope:
            scope_name = chosen_scope
        for cond in spec['conditions']:
            if not _post_on(post, _field_key(slot, cond['key'])):
                continue
            if not cond.get('needs_value'):
                conditions[cond['key']] = None
                continue
            posted = _post_value(post, _field_key(slot, cond['key']))
            if cond['key'] == BRONZE_PACK_KEY:
                if posted is not None and posted > 0:
                    conditions[cond['key']] = posted
                continue
            if posted is not None:
                conditions[cond['key']] = posted
            elif cond['key'] not in conditions:
                conditions[cond['key']] = None
    return action_value, scope_name, conditions


def _emit_shared(slot, spec, profile):
    action_value, scope_name, conditions = profile
    rows = []
    value = action_value if spec.get('needs_value') else None
    _append(rows, spec['key'], value, slot)
    if spec.get('scope'):
        _append(rows, SCOPE_KEYS[scope_name], None, slot)
    for cond in spec['conditions']:
        if cond['key'] not in conditions:
            continue
        _append(rows, cond['key'], conditions[cond['key']], slot)
    return rows


def _posted_slots(post):
    if hasattr(post, 'getlist'):
        return [item for item in post.getlist('queue_slot') if str(item).strip() != '']
    raw = post.get('queue_slot')
    if raw is None or str(raw).strip() == '':
        return []
    return [raw]


def modes_from_post(post):
    items = []
    _emit_session(items, SESSION_PREFIX, post)
    chosen = _checked_cards(post)
    slots_by_key = {}
    for slot, key in chosen:
        slots_by_key.setdefault(key, []).append(slot)
    profiles = {}
    for key, slots in slots_by_key.items():
        profiles[key] = _shared_profile(post, ACTION_BY_KEY[key], slots)
    for slot, key in chosen:
        items.extend(_emit_shared(slot, ACTION_BY_KEY[key], profiles[key]))
    _emit_session(items, SESSION_SUFFIX, post)
    return items


def modes_to_text(items):
    lines = []
    for item in items or []:
        title = KEY_TITLES.get(item['key'])
        if not title:
            continue
        value = item.get('value')
        if value is None:
            lines.append('%s+' % title)
        else:
            lines.append('%s%s' % (title, value))
    return '\n'.join(lines)


def selected_map(modes):
    return {item['key']: item.get('value') for item in normalize_modes(modes)}


def _clean_item(item):
    normalized = normalize_mode_item(item)
    if normalized is None:
        return None
    slot = item.get('slot') if isinstance(item, dict) else None
    if slot is not None:
        try:
            slot = int(slot)
        except (TypeError, ValueError):
            slot = None
    return {'key': normalized['key'], 'value': normalized['value'], 'slot': slot}


def _blank_group(key, slot, value, checked):
    return {
        'key': key,
        'slot': slot,
        'value': value,
        'conditions': {},
        'sbc_scope': 'all',
        'checked': checked,
    }


def _attach(group, key, value):
    scope_name = SCOPE_BY_KEY.get(key)
    if scope_name is not None:
        group['sbc_scope'] = scope_name
        return
    group['conditions'][key] = value


def _queue_groups(modes):
    groups = []
    current = None
    for raw in modes or []:
        item = _clean_item(raw)
        if item is None:
            continue
        key = item['key']
        if key in SESSION_KEY_SET:
            continue
        if key in ACTION_BY_KEY:
            same_slot = (
                current is not None
                and item['slot'] is not None
                and current['slot'] == item['slot']
                and current['key'] == key
            )
            if same_slot:
                current['value'] = item['value']
                continue
            current = _blank_group(key, item['slot'], item['value'], True)
            groups.append(current)
            continue
        owner = CONDITION_OWNER.get(key)
        if owner is None:
            continue
        same_owner = (
            current is not None
            and current['key'] == owner
            and (
                item['slot'] is None
                or current['slot'] is None
                or current['slot'] == item['slot']
            )
        )
        if same_owner:
            if item['slot'] is not None:
                current['slot'] = item['slot']
            _attach(current, key, item['value'])
            continue
        current = _blank_group(owner, item['slot'], None, True)
        _attach(current, key, item['value'])
        groups.append(current)
    return groups


def _share_groups(groups):
    by_key = {}
    for group in groups:
        by_key.setdefault(group['key'], []).append(group)
    for copies in by_key.values():
        checked = [group for group in copies if group['checked']]
        if not checked:
            continue
        conditions = {}
        scope = 'all'
        value = None
        for group in checked:
            scope = group['sbc_scope']
            if group['value'] is not None:
                value = group['value']
            for key, cond_value in group['conditions'].items():
                if key not in conditions or cond_value is not None:
                    conditions[key] = cond_value
        for group in copies:
            group['conditions'] = dict(conditions)
            group['sbc_scope'] = scope
            if value is not None:
                group['value'] = value


def _merge_queue(groups):
    present = {group['key'] for group in groups}
    result = []
    index = 0
    used = {group['slot'] for group in groups if group['slot'] is not None}
    nxt = [1]

    def take_slot():
        while nxt[0] in used:
            nxt[0] += 1
        slot = nxt[0]
        used.add(slot)
        nxt[0] += 1
        return slot

    for group in groups:
        target = QUEUE_INDEX[group['key']]
        while index < target:
            key = QUEUE_ORDER[index]
            index += 1
            if key not in present:
                result.append(_blank_group(key, take_slot(), None, False))
        if group['slot'] is None:
            group['slot'] = take_slot()
        result.append(group)
        if index <= target:
            index = target + 1
    while index < len(QUEUE_ORDER):
        key = QUEUE_ORDER[index]
        index += 1
        if key not in present:
            result.append(_blank_group(key, take_slot(), None, False))
    return result


def _editor_card(group):
    spec = ACTION_BY_KEY[group['key']]
    conditions = []
    for cond in spec['conditions']:
        row = dict(cond)
        row['checked'] = cond['key'] in group['conditions']
        row['value'] = group['conditions'].get(cond['key'])
        conditions.append(row)
    return {
        'key': spec['key'],
        'title': spec['title'],
        'slot': group['slot'],
        'needs_value': spec.get('needs_value', False),
        'scope': spec.get('scope', False),
        'checked': group['checked'],
        'value': group['value'],
        'sbc_scope': group['sbc_scope'],
        'conditions': conditions,
    }


def _scope_lines(group, spec):
    if not spec.get('scope'):
        return []
    scope_key = SCOPE_KEYS.get(group['sbc_scope']) or SCOPE_KEYS['all']
    return [{
        'key': scope_key,
        'title': KEY_TITLES[scope_key],
        'value': None,
    }]


def modes_preview(modes):
    selected = selected_map(modes)
    session = [
        {
            'key': item['key'],
            'title': item['title'],
            'value': selected.get(item['key']),
        }
        for item in SESSION_ITEMS
        if item['key'] in selected
    ]
    actions = []
    for group in _queue_groups(modes):
        spec = ACTION_BY_KEY[group['key']]
        conditions = _scope_lines(group, spec)
        for cond in spec['conditions']:
            if cond['key'] not in group['conditions']:
                continue
            conditions.append({
                'key': cond['key'],
                'title': cond['title'],
                'value': group['conditions'][cond['key']],
            })
        actions.append({
            'key': spec['key'],
            'title': spec['title'],
            'value': group['value'],
            'conditions': conditions,
        })
    return {'session': session, 'actions': actions}


def editor_state(modes):
    selected = selected_map(modes)
    groups = _merge_queue(_queue_groups(modes))
    _share_groups(groups)
    first_sbc = next(
        (group for group in groups if group['key'] == 'collectSBC' and group['checked']),
        None,
    )
    session = []
    for item in SESSION_ITEMS:
        row = dict(item)
        row['checked'] = item['key'] in selected
        row['value'] = selected.get(item['key'])
        session.append(row)
    return {
        'session': session,
        'actions': [_editor_card(group) for group in groups],
        'sbc_scope': first_sbc['sbc_scope'] if first_sbc else 'all',
        'scope_options': [
            {'value': 'all', 'title': KEY_TITLES['collectAllSbc']},
            {'value': 'priority', 'title': KEY_TITLES['collectPrioritySbc']},
            {'value': 'notPriority', 'title': KEY_TITLES['collectNotPrioritySbc']},
        ],
    }
