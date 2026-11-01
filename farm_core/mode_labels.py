MODE_TITLES = {
    'Собрать задания': 'collectObjectives',
    'Зайти в трансферный список и очистить проданных': 'checkTransferList',
    'Открыть паки': 'openPacks',
    'Открыть паки предпросмотра': 'openPreviewPack',
    'Продать игроков': 'sellPlayers',
    'Собрать СБЧ': 'collectSBC',
    'Проверить нужно ли купить контракты': 'checkIfNeedToBuyContracts',
    'Обновить состав': 'setSquad',
    'Перезагружаться если трансферный список полон (иначе закрывает акк)': 'reloadPageIfFullTransferList',
    'Открывать продаваемые паки': 'openTradablePacks',
    'Открывать непродаваемые паки': 'openUnTradablePacks',
    'Квиксел игрока после того как он не продался по минимальной цене рейтинг ниже включ.': 'quickSellIfNotSell',
    'Отправить айтемы из клуба в трансферный список (работает только когда собраны все СБЧ)': 'sendClubItemsToTransferList',
    'Проверить открылся ли рынок': 'checkMarketOpened',
    'Открыть следующий аккаунт после завершения работы': 'freeAccountSolving',
    'Начать снайп': 'startSnipe',
    'Открыть непродаваемые паки после круга сборки бесконечных СБЧ': 'openUntradeablePackAfterOneRound',
    'Продажа по футбин из паков': 'sellFutBinFromPacks',
    'Докупить нехватающих в состав': 'buyNotEnoughInSquad',
    'Квиксел если по мин не продался айтем': 'quickSellIfMinNotSold',
    'Нажать на кнопку перевыставить всех': 'relistAll',
    'Открыть фри пак из стора': 'open10coinsPacks',
    'Только СБЧ из клуба/дубликатов': 'sbcOnlyClubStorage',
    'Собрать состязания': 'collectCompetitions',
    'Закрывать если превышено допустимое количество запросов': 'closeIfRequestAllowedExceeded',
    'Разобрать нераспределенные': 'handleUnsigned',
    'Собрать все сбч': 'collectAllSbc',
    'Собрать сбч приоритет': 'collectPrioritySbc',
    'Собрать сбч без приоритета': 'collectNotPrioritySbc',
    'Если не собрал приоритет пробует собирать все СБЧ': 'priorityFailsCollectAll',
    'Собрать СБЧ если список дубликатов достиг сто': 'solveIf100duplicate',
    'Не брать игроков для сбч из состава': 'doNotTakePlayerFromSquadToSbc',
    'Квиксел арендных игроков из клуба': 'quickSellLoanFromClub',
    'Не открывать продаваемые паки если количество игроков в трансферном списке больше': 'doNotOpenPackInPlEx',
    'Собрать СБЧ не приоритет за круг максимум': 'collectSBCnotPriorityMax',
    'Квикселить непродаваемые дубликаты серебро/бронза': 'quickSellSilverBronzeDublicat',
    'Квиксел по рейтингу ниже и включительно': 'quickSellRatingBelowAndEqual',
    'Квиксел редких с низкой ценой': 'quickSellRareGoldLowPricePlayers',
    'За 24 часа можно сделать запросов': 'requests24hours',
    'Первый заход в вебку': 'firstLoginToWeb',
    'Проверка бана на входе в вебку': 'checkBanOnLogin',
    'Сбросить запросы в': 'resetRequests',
    'Использовать продаваемых бронзовых за двести для сбч': 'useBronze200ForSbc',
    'Открыть бронзовые паки из магазина': 'openBronzePacksFromStore',
}


MANGLED_REQUESTS24 = 'За  часа можно сделать запросов'


def _int_or_none(raw):
    if raw is None or raw == '':
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if text.isdigit():
        return int(text)
    return None


def _requests24_from_mangled(value):
    number = _int_or_none(value)
    if number is None:
        return None
    text = str(number)
    if text == '24':
        return None
    if text.startswith('24') and len(text) > 2 and text[2:].isdigit():
        return int(text[2:])
    return number


def parse_mode_line(line):
    raw = (line or '').replace('\r', '').replace('+', '').strip()
    if not raw:
        return None
    if raw.startswith(MANGLED_REQUESTS24):
        rest = raw[len(MANGLED_REQUESTS24):].strip()
        if not rest or rest.isdigit():
            value = _requests24_from_mangled(rest)
            if value is None:
                return None
            return {
                'key': 'requests24hours',
                'value': value,
                'unknown': False,
                'title_ru': 'За 24 часа можно сделать запросов',
            }
    for title in sorted(MODE_TITLES, key=len, reverse=True):
        if raw != title and not raw.startswith(title):
            continue
        rest = raw[len(title):].strip()
        if rest and not rest.isdigit():
            continue
        return {
            'key': MODE_TITLES[title],
            'value': int(rest) if rest else None,
            'unknown': False,
            'title_ru': title,
        }
    number = ''.join(ch for ch in raw if ch.isdigit())
    title = ''.join(ch for ch in raw if not ch.isdigit()).strip()
    return {'key': title, 'value': number, 'unknown': True, 'title_ru': title}


def parse_modes_text(text):
    items = []
    for line in (text or '').splitlines():
        parsed = parse_mode_line(line)
        if parsed is not None:
            items.append(parsed)
    return items


def normalize_mode_item(item):
    if not item:
        return None
    key = item.get('key')
    value = item.get('value')
    if key == MANGLED_REQUESTS24:
        value = _requests24_from_mangled(value)
        if value is None:
            return None
        return {'key': 'requests24hours', 'value': value}
    return {'key': key, 'value': value}


def normalize_modes(items):
    result = []
    for item in items or []:
        normalized = normalize_mode_item(item)
        if normalized is not None:
            result.append(normalized)
    return result
