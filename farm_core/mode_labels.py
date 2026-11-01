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


def parse_mode_line(line):
    raw = (line or '').replace('\r', '').strip()
    if not raw:
        return None
    number = ''.join(ch for ch in raw if ch.isdigit())
    title = ''.join(ch for ch in raw if not ch.isdigit() and ch != '+').strip()
    key = MODE_TITLES.get(title)
    if key is None:
        return {'key': title, 'value': number, 'unknown': True, 'title_ru': title}
    value = int(number) if number else None
    return {'key': key, 'value': value, 'unknown': False, 'title_ru': title}


def parse_modes_text(text):
    items = []
    for line in (text or '').splitlines():
        parsed = parse_mode_line(line)
        if parsed is not None:
            items.append(parsed)
    return items
