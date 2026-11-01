from farm_core.mode_labels import MODE_TITLES, normalize_modes

KEY_TITLES = {key: title for title, key in MODE_TITLES.items()}

SESSION_ITEMS = (
    {'key': 'firstLoginToWeb', 'title': KEY_TITLES['firstLoginToWeb']},
    {'key': 'checkBanOnLogin', 'title': KEY_TITLES['checkBanOnLogin']},
    {'key': 'checkMarketOpened', 'title': KEY_TITLES['checkMarketOpened']},
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
    {'key': 'collectObjectives', 'title': KEY_TITLES['collectObjectives']},
    {'key': 'handleUnsigned', 'title': KEY_TITLES['handleUnsigned']},
    {'key': 'freeAccountSolving', 'title': KEY_TITLES['freeAccountSolving']},
)

ACTION_CARDS = (
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

SAVE_ORDER = (
    'firstLoginToWeb',
    'checkBanOnLogin',
    'checkMarketOpened',
    'collectObjectives',
    'collectSBC',
    'collectAllSbc',
    'collectPrioritySbc',
    'collectNotPrioritySbc',
    'priorityFailsCollectAll',
    'solveIf100duplicate',
    'doNotTakePlayerFromSquadToSbc',
    'useBronze200ForSbc',
    'collectSBCnotPriorityMax',
    'sbcOnlyClubStorage',
    'openPacks',
    'openTradablePacks',
    'openUnTradablePacks',
    'open10coinsPacks',
    'openUntradeablePackAfterOneRound',
    'doNotOpenPackInPlEx',
    'openBronzePacksFromStore',
    'openPreviewPack',
    'handleUnsigned',
    'sellPlayers',
    'quickSellIfNotSell',
    'quickSellIfMinNotSold',
    'quickSellSilverBronzeDublicat',
    'quickSellRatingBelowAndEqual',
    'quickSellRareGoldLowPricePlayers',
    'quickSellLoanFromClub',
    'checkTransferList',
    'relistAll',
    'startSnipe',
    'resetRequests',
    'requests24hours',
    'closeIfRequestAllowedExceeded',
    'reloadPageIfFullTransferList',
    'freeAccountSolving',
)


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


def _append(items, key, value=None):
    items.append({'key': key, 'value': value})


def modes_from_post(post):
    picked = {}
    for item in SESSION_ITEMS:
        key = item['key']
        if _post_on(post, key):
            picked[key] = _post_value(post, key) if item.get('needs_value') else None
    for card in ACTION_CARDS:
        if not _post_on(post, card['key']):
            continue
        picked[card['key']] = _post_value(post, card['key']) if card.get('needs_value') else None
        if card.get('scope'):
            scope_name = post.get('sbc_scope') or 'all'
            scope_key = SCOPE_KEYS.get(scope_name) or SCOPE_KEYS['all']
            picked[scope_key] = None
        for cond in card['conditions']:
            if not _post_on(post, cond['key']):
                continue
            picked[cond['key']] = (
                _post_value(post, cond['key']) if cond.get('needs_value') else None
            )
    items = []
    for key in SAVE_ORDER:
        if key in picked:
            _append(items, key, picked[key])
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


def _preview_item(spec, selected):
    key = spec['key']
    return {
        'key': key,
        'title': spec['title'],
        'value': selected.get(key),
    }


def modes_preview(modes):
    selected = selected_map(modes)
    session = [
        _preview_item(item, selected)
        for item in SESSION_ITEMS
        if item['key'] in selected
    ]
    actions = []
    for card in ACTION_CARDS:
        if card['key'] not in selected:
            continue
        conditions = []
        if card.get('scope'):
            shown_scope = False
            for scope_key in SCOPE_KEYS.values():
                if scope_key in selected:
                    conditions.append({
                        'key': scope_key,
                        'title': KEY_TITLES[scope_key],
                        'value': None,
                    })
                    shown_scope = True
            if not shown_scope:
                conditions.append({
                    'key': 'collectAllSbc',
                    'title': KEY_TITLES['collectAllSbc'],
                    'value': None,
                })
        for cond in card['conditions']:
            if cond['key'] in selected:
                conditions.append(_preview_item(cond, selected))
        actions.append({
            'key': card['key'],
            'title': card['title'],
            'value': selected.get(card['key']),
            'conditions': conditions,
        })
    return {'session': session, 'actions': actions}


def editor_state(modes):
    selected = selected_map(modes)
    if 'collectPrioritySbc' in selected:
        sbc_scope = 'priority'
    elif 'collectNotPrioritySbc' in selected:
        sbc_scope = 'notPriority'
    else:
        sbc_scope = 'all'
    session = []
    for item in SESSION_ITEMS:
        row = dict(item)
        row['checked'] = item['key'] in selected
        row['value'] = selected.get(item['key'])
        session.append(row)
    actions = []
    for card in ACTION_CARDS:
        row = {
            'key': card['key'],
            'title': card['title'],
            'needs_value': card.get('needs_value', False),
            'scope': card.get('scope', False),
            'checked': card['key'] in selected,
            'value': selected.get(card['key']),
            'conditions': [],
        }
        for cond in card['conditions']:
            cond_row = dict(cond)
            cond_row['checked'] = cond['key'] in selected
            cond_row['value'] = selected.get(cond['key'])
            row['conditions'].append(cond_row)
        actions.append(row)
    return {
        'session': session,
        'actions': actions,
        'sbc_scope': sbc_scope,
        'scope_options': [
            {'value': 'all', 'title': KEY_TITLES['collectAllSbc']},
            {'value': 'priority', 'title': KEY_TITLES['collectPrioritySbc']},
            {'value': 'notPriority', 'title': KEY_TITLES['collectNotPrioritySbc']},
        ],
    }
