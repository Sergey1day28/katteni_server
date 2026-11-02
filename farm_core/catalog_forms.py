import json
import logging

from farm_core.models import (
    MarketFilter,
    MarketFilterList,
    SbcSet,
    SbcSetItem,
    SbcTemplate,
    SnipeSettingsDoc,
)

logger = logging.getLogger(__name__)

MARKET_CHOICES = ('equal', 'below', 'above', 'notForSale')
PLAYER_SET_KIND = 'playerSet'
SBC_FLAGS = (
    ('onlyPlayerFromClub', 'из клуба'),
    ('onlyPlayerFromStorage', 'из дубликатов'),
    ('useSbcSolver', 'авто решение'),
    ('solveIfMoreThan100Duplicates', 'если 100 дублей'),
    ('takeSpecialCardsForSolver', 'особые карты'),
)


def snipe_form_values(raw):
    preferences = _preferences(raw)
    time_from = _clock_text(
        preferences.get('timeSnipeFrom'),
        preferences.get('timeSnipeFromMin'),
        '20:00',
    )
    time_to = _clock_text(
        preferences.get('timeSnipeTo'),
        preferences.get('timeSnipeToMin'),
        '07:00',
    )
    return {
        'pause_from': _int(preferences.get('requestPauseFrom'), 500, 0, 60000),
        'pause_to': _int(preferences.get('requestPauseTo'), 1000, 0, 60000),
        'time_from': time_from,
        'time_to': time_to,
        'long_pause': _int(preferences.get('longPause'), 60, 0, 3600),
        'requests_before_pause': _int(preferences.get('timeToPause'), 50, 0, 10000),
        'purchases_stop': _int(preferences.get('purchasesStop'), 0, 0, 1000),
        'result_stop': _int(preferences.get('resultCountToStop'), 22, 1, 50),
        'change_min_bin': _flag(preferences.get('changeMinBin'), True),
        'auto_sell': _flag(preferences.get('autoSell'), True),
        'change_filters': _flag(preferences.get('changeFilters'), True),
        'filters_from_server': _flag(preferences.get('setFiltersFromServer'), True),
        'market': _market(preferences.get('marketPrice')),
    }


def save_snipe_form(post, updated_by):
    current = SnipeSettingsDoc.current()
    previous = current.payload if current else ''
    payload = _pack_snipe(post, previous)
    doc = SnipeSettingsDoc.write(payload, updated_by=updated_by)
    logger.info('Сохранены настройки снайпа, версия %s', doc.version)
    return 'Настройки снайпа сохранены, версия %s' % doc.version


def market_row_view(item):
    body = item.payload if isinstance(item.payload, dict) else {}
    return {
        'item': item,
        'market': _market(body.get('market')),
        'change_min_bin': _flag(body.get('changeMinBin'), False),
    }


def save_market_row(filter_id, post, updated_by):
    item = MarketFilter.objects.filter(id=_pk(filter_id)).first()
    if item is None:
        return 'Фильтр не найден'
    body = dict(item.payload) if isinstance(item.payload, dict) else {}
    body['market'] = _market(post.get('market'))
    body['changeMinBin'] = post.get('change_min_bin') == '1'
    item.payload = body
    item.enabled = post.get('enabled') == '1'
    item.position = _int(post.get('position'), item.position, 0, 9999)
    item.version += 1
    item.updated_by = updated_by
    item.save(update_fields=['payload', 'enabled', 'position', 'version', 'updated_by', 'updated_at'])
    _bump_market_list()
    logger.info('Фильтр рынка «%s» обновлён', item.title)
    return 'Фильтр «%s» сохранён' % item.title


def remove_market_row(filter_id):
    item = MarketFilter.objects.filter(id=_pk(filter_id)).first()
    if item is None:
        return 'Фильтр не найден'
    title = item.title
    item.delete()
    _bump_market_list()
    logger.info('Фильтр рынка «%s» удалён', title)
    return 'Фильтр «%s» удалён' % title


def selected_sbc(set_id, tile_id):
    sbc_set = SbcSet.objects.filter(id=_pk(set_id)).first()
    if sbc_set is None:
        return None
    rows = list(sbc_set.items.select_related('template').order_by('position', 'id'))
    chosen = None
    for row in rows:
        if _pk(tile_id) is not None and row.template_id == _pk(tile_id):
            chosen = row
    view = _tile_view(chosen) if chosen else None
    return {
        'set': sbc_set,
        'rows': rows,
        'item': chosen,
        'view': view,
    }


def save_sbc_tile(set_id, template_id, post, updated_by):
    sbc_set = SbcSet.objects.filter(id=_pk(set_id)).first()
    template = SbcTemplate.objects.filter(id=_pk(template_id)).first()
    if sbc_set is None or template is None:
        return 'Набор или плитка не найдены'
    link = SbcSetItem.objects.filter(sbc_set=sbc_set, template=template).first()
    if link is None:
        return 'Плитки нет в этом наборе'
    payload = json.loads(json.dumps(template.payload or {}))
    data = _sbc_data(payload)
    if data is None:
        return 'В плитке нет данных для правки'
    for key, _label in SBC_FLAGS:
        data[key] = post.get(key) == '1'
    data['maxRatingForSolver'] = _int(post.get('maxRatingForSolver'), 0, 0, 99)
    player = data.get('kind') == PLAYER_SET_KIND
    current_times = data.get('timesPerDay')
    if current_times is None:
        current_times = template.times_per_day or 3
    times = _int(post.get('timesPerDay'), current_times, 0, 99)
    if player:
        data['timesPerDay'] = times
    filters = data.get('filters')
    if isinstance(filters, list):
        count = _int(post.get('slot_count'), len(filters), 0, 50)
        for index in range(min(count, len(filters))):
            slot = filters[index]
            if not isinstance(slot, dict):
                continue
            rating = slot.get('rating')
            if not isinstance(rating, dict):
                rating = {}
                slot['rating'] = rating
            rating['min'] = _int(post.get('min-%s' % index), rating.get('min') or 0, 0, 100)
            rating['max'] = _int(post.get('max-%s' % index), rating.get('max') or 100, 0, 100)
            if player:
                slot['count'] = _int(post.get('count-%s' % index), slot.get('count') or 1, 0, 23)
            else:
                slot['futBinPercent'] = _int(
                    post.get('percent-%s' % index),
                    slot.get('futBinPercent') or 100,
                    0,
                    100,
                )
    payload_changed = payload != json.loads(json.dumps(template.payload or {}))
    priority = post.get('priority') == '1'
    priority_changed = link.priority != priority
    if payload_changed:
        template.payload = payload
        template.version += 1
        template.updated_by = updated_by
        update = ['payload', 'version', 'updated_by', 'updated_at']
        if player:
            template.times_per_day = times
            update.append('times_per_day')
        template.save(update_fields=update)
        _bump_sets_with_template(template)
        logger.info('Плитка СБЧ «%s» обновлена, версия %s', template.name, template.version)
    elif player and template.times_per_day != times:
        template.times_per_day = times
        template.save(update_fields=['times_per_day', 'updated_at'])
    if priority_changed:
        link.priority = priority
        link.save(update_fields=['priority'])
        if not payload_changed:
            _bump_set(sbc_set)
        logger.info('Приоритет плитки «%s» в наборе «%s»: %s', template.name, sbc_set.name, priority)
    if not payload_changed and not priority_changed:
        return 'Плитка «%s» без изменений' % template.name
    return 'Плитка «%s» сохранена' % template.name


def _pack_snipe(post, previous_raw):
    preferences = dict(_preferences(previous_raw))
    preferences.setdefault('sendToTransfer', 1)
    preferences.setdefault('signalSnipe', 0)
    preferences.setdefault('resetMarket', 0)
    preferences['requestPauseFrom'] = _int(post.get('pause_from'), 500, 0, 60000)
    preferences['requestPauseTo'] = _int(post.get('pause_to'), 1000, 0, 60000)
    preferences['longPause'] = _int(post.get('long_pause'), 60, 0, 3600)
    preferences['timeToPause'] = _int(post.get('requests_before_pause'), 50, 0, 10000)
    preferences['purchasesStop'] = _int(post.get('purchases_stop'), 0, 0, 1000)
    preferences['resultCountToStop'] = _int(post.get('result_stop'), 22, 1, 50)
    preferences['changeMinBin'] = 1 if post.get('change_min_bin') == '1' else 0
    preferences['autoSell'] = 1 if post.get('auto_sell') == '1' else 0
    preferences['changeFilters'] = 1 if post.get('change_filters') == '1' else 0
    preferences['setFiltersFromServer'] = 1 if post.get('filters_from_server') == '1' else 0
    preferences['marketPrice'] = _market(post.get('market'))
    hour_from, minute_from = _split_clock(post.get('time_from'), 20, 0)
    hour_to, minute_to = _split_clock(post.get('time_to'), 7, 0)
    preferences['timeSnipeFrom'] = hour_from
    preferences['timeSnipeFromMin'] = minute_from
    preferences['timeSnipeTo'] = hour_to
    preferences['timeSnipeToMin'] = minute_to
    mode = 'manual'
    parsed = _json_object(previous_raw)
    if isinstance(parsed.get('mode'), str) and parsed.get('mode'):
        mode = parsed['mode']
    return json.dumps({'mode': mode, 'preferences': preferences}, ensure_ascii=False)


def _preferences(raw):
    parsed = _json_object(raw)
    preferences = parsed.get('preferences')
    if isinstance(preferences, dict):
        return preferences
    return parsed


def _json_object(raw):
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _tile_view(link):
    data = _sbc_data(link.template.payload) or {}
    filters = data.get('filters') if isinstance(data.get('filters'), list) else []
    player = data.get('kind') == PLAYER_SET_KIND
    slots = []
    for index, slot in enumerate(filters):
        if not isinstance(slot, dict):
            continue
        rating = slot.get('rating') if isinstance(slot.get('rating'), dict) else {}
        slots.append({
            'index': index,
            'name': slot.get('ruName') or slot.get('name') or ('Слот %s' % (index + 1)),
            'title': slot.get('title') or '',
            'min': _int(rating.get('min'), 0, 0, 100),
            'max': _int(rating.get('max'), 100, 0, 100),
            'percent': _int(slot.get('futBinPercent'), 100, 0, 100),
            'count': _int(slot.get('count'), 1, 0, 23),
        })
    also = list(
        SbcSet.objects.filter(items__template=link.template)
        .exclude(id=link.sbc_set_id)
        .order_by('name')
        .values_list('name', flat=True)
    )
    return {
        'name': link.template.name,
        'player': player,
        'slots': slots,
        'flags': [
            {'key': key, 'label': label, 'checked': _flag(data.get(key), False)}
            for key, label in SBC_FLAGS
        ],
        'max_rating': _int(data.get('maxRatingForSolver'), 0, 0, 99),
        'times_per_day': _int(
            data.get('timesPerDay') if data.get('timesPerDay') is not None else link.template.times_per_day,
            3,
            0,
            99,
        ),
        'priority': link.priority,
        'also': also,
        'slot_count': len(filters),
    }


def _sbc_data(payload):
    if not isinstance(payload, dict):
        return None
    sbc = payload.get('sbc')
    if isinstance(sbc, dict) and isinstance(sbc.get('data'), dict):
        return sbc['data']
    if isinstance(payload.get('data'), dict):
        return payload['data']
    return None


def _bump_market_list():
    listing, _created = MarketFilterList.objects.get_or_create(pk=1, defaults={'version': 1})
    listing.version += 1
    listing.save(update_fields=['version', 'updated_at'])


def _bump_sets_with_template(template):
    seen = set()
    for link in template.set_items.select_related('sbc_set'):
        if link.sbc_set_id in seen:
            continue
        seen.add(link.sbc_set_id)
        _bump_set(link.sbc_set)


def _bump_set(sbc_set):
    sbc_set.version += 1
    sbc_set.save(update_fields=['version', 'updated_at'])


def _clock_text(hour, minute, default):
    if hour is None and minute is None:
        return default
    return '%02d:%02d' % (_int(hour, 0, 0, 23), _int(minute, 0, 0, 59))


def _split_clock(value, default_hour, default_minute):
    text = str(value or '')
    parts = text.split(':')
    if len(parts) < 2:
        return default_hour, default_minute
    return _int(parts[0], default_hour, 0, 23), _int(parts[1], default_minute, 0, 59)


def _market(value):
    return value if value in MARKET_CHOICES else 'equal'


def _flag(value, default):
    if value is None:
        return default
    return value in (True, 1, '1')


def _pk(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int(value, default, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))
