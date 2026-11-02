from django.http import QueryDict
from django.test import SimpleTestCase

from farm_core.mode_catalog import editor_state, modes_from_post, modes_preview, modes_to_text
from farm_core.mode_labels import normalize_modes, parse_mode_line, parse_modes_text


class ModeCatalogTests(SimpleTestCase):
    def test_условия_сбч_без_действия_не_пишем(self):
        post = QueryDict(mutable=True)
        post['mode_useBronze200ForSbc'] = '1'
        post['sbc_scope'] = 'priority'
        self.assertEqual(modes_from_post(post), [])

    def test_следующий_аккаунт_последний(self):
        post = QueryDict(mutable=True)
        post['mode_freeAccountSolving'] = '1'
        post['mode_collectSBC'] = '1'
        post['mode_firstLoginToWeb'] = '1'
        keys = [item['key'] for item in modes_from_post(post)]
        self.assertEqual(keys[0], 'firstLoginToWeb')
        self.assertEqual(keys[1], 'collectSBC')
        self.assertIn('collectAllSbc', keys)
        self.assertEqual(keys[-1], 'freeAccountSolving')

    def test_бронза_из_магазина_только_с_паками(self):
        post = QueryDict(mutable=True)
        post['mode_openBronzePacksFromStore'] = '1'
        post['mode_value_openBronzePacksFromStore'] = '1'
        self.assertEqual(modes_from_post(post), [])
        post['mode_openPacks'] = '1'
        keys = [item['key'] for item in modes_from_post(post)]
        self.assertEqual(keys, ['openPacks', 'openBronzePacksFromStore'])
        self.assertEqual(modes_from_post(post)[1]['value'], 1)

    def test_сброс_часа_только_со_снайпом(self):
        post = QueryDict(mutable=True)
        post['mode_resetRequests'] = '1'
        post['mode_value_resetRequests'] = '3'
        self.assertEqual(modes_from_post(post), [])
        post['mode_startSnipe'] = '1'
        items = modes_from_post(post)
        self.assertEqual(
            items,
            [
                {'key': 'startSnipe', 'value': None},
                {'key': 'resetRequests', 'value': 3},
            ],
        )

    def test_лимит_запросов_не_съедает_24_из_названия(self):
        parsed = parse_mode_line('За 24 часа можно сделать запросов650+')
        self.assertEqual(parsed['key'], 'requests24hours')
        self.assertEqual(parsed['value'], 650)
        self.assertFalse(parsed['unknown'])

    def test_кривой_ключ_после_выдирания_цифр(self):
        parsed = parse_mode_line('За  часа можно сделать запросов24650')
        self.assertEqual(parsed['key'], 'requests24hours')
        self.assertEqual(parsed['value'], 650)
        self.assertFalse(parsed['unknown'])
        self.assertIsNone(parse_mode_line('За  часа можно сделать запросов24'))

    def test_собрать_сбч_не_путается_с_длинным_названием(self):
        parsed = parse_mode_line('Собрать СБЧ+')
        self.assertEqual(parsed['key'], 'collectSBC')
        self.assertIsNone(parsed['value'])

    def test_текст_модов_крутится_туда_обратно(self):
        text = modes_to_text([
            {'key': 'collectSBC', 'value': None},
            {'key': 'requests24hours', 'value': 650},
        ])
        items = parse_modes_text(text)
        self.assertEqual(
            [(item['key'], item['value']) for item in items],
            [('collectSBC', None), ('requests24hours', 650)],
        )
        self.assertFalse(any(item.get('unknown') for item in items))

    def test_нормализует_кривой_ключ_из_sqlite(self):
        items = normalize_modes([
            {'key': 'За  часа можно сделать запросов', 'value': '24650'},
            {'key': 'collectSBC', 'value': None},
        ])
        self.assertEqual(
            items,
            [
                {'key': 'requests24hours', 'value': 650},
                {'key': 'collectSBC', 'value': None},
            ],
        )

    def test_редактор_видит_кривой_лимит(self):
        state = editor_state([
            {'key': 'За  часа можно сделать запросов', 'value': '24650'},
        ])
        row = [item for item in state['session'] if item['key'] == 'requests24hours'][0]
        self.assertTrue(row['checked'])
        self.assertEqual(row['value'], 650)

    def test_текст_модов_для_старого_разбора(self):
        items = [
            {'key': 'collectSBC', 'value': None},
            {'key': 'requests24hours', 'value': 650},
        ]
        text = modes_to_text(items)
        self.assertIn('Собрать СБЧ+', text)
        self.assertIn('За 24 часа можно сделать запросов650', text)

    def test_превью_группирует_действие_и_сессию(self):
        preview = modes_preview([
            {'key': 'collectSBC', 'value': None},
            {'key': 'useBronze200ForSbc', 'value': None},
            {'key': 'requests24hours', 'value': 650},
            {'key': 'freeAccountSolving', 'value': None},
        ])
        session_titles = [item['title'] for item in preview['session']]
        self.assertIn('За 24 часа можно сделать запросов', session_titles)
        self.assertIn('Открыть следующий аккаунт после завершения работы', session_titles)
        self.assertEqual(preview['actions'][0]['key'], 'collectSBC')
        nested = [item['title'] for item in preview['actions'][0]['conditions']]
        self.assertEqual(
            nested,
            [
                'Собрать все сбч',
                'Использовать продаваемых бронзовых за двести для сбч',
            ],
        )

    def test_собрать_сбч_пишет_один_scope(self):
        post = QueryDict(mutable=True)
        post['mode_collectSBC'] = '1'
        self.assertEqual(
            [item['key'] for item in modes_from_post(post)],
            ['collectSBC', 'collectAllSbc'],
        )
        post['sbc_scope'] = 'priority'
        self.assertEqual(
            [item['key'] for item in modes_from_post(post)],
            ['collectSBC', 'collectPrioritySbc'],
        )
        post['sbc_scope'] = 'notPriority'
        self.assertEqual(
            [item['key'] for item in modes_from_post(post)],
            ['collectSBC', 'collectNotPrioritySbc'],
        )

    def test_очередь_держит_свой_порядок(self):
        post = QueryDict(mutable=True)
        post.setlist('queue_slot', ['2', '1'])
        post['queue_key_2'] = 'openPacks'
        post['queue_key_1'] = 'collectSBC'
        post['mode_2_openPacks'] = '1'
        post['mode_2_openUnTradablePacks'] = '1'
        post['mode_1_collectSBC'] = '1'
        post['sbc_scope_1'] = 'priority'
        post['mode_freeAccountSolving'] = '1'
        items = modes_from_post(post)
        self.assertEqual(
            [item['key'] for item in items],
            [
                'openPacks',
                'openUnTradablePacks',
                'collectSBC',
                'collectPrioritySbc',
                'freeAccountSolving',
            ],
        )
        self.assertEqual(items[0]['slot'], 2)
        self.assertEqual(items[-1].get('slot'), None)

    def test_вторая_карточка_паков_это_бронза(self):
        post = QueryDict(mutable=True)
        post.setlist('queue_slot', ['1', '2'])
        post['queue_key_1'] = 'openPacks'
        post['queue_key_2'] = 'openPacks'
        post['mode_1_openPacks'] = '1'
        post['mode_1_openUnTradablePacks'] = '1'
        post['mode_2_openPacks'] = '1'
        post['mode_2_openBronzePacksFromStore'] = '1'
        post['mode_value_2_openBronzePacksFromStore'] = '4'
        self.assertEqual(
            [(item['key'], item['value'], item['slot']) for item in modes_from_post(post)],
            [
                ('openPacks', None, 1),
                ('openUnTradablePacks', None, 1),
                ('openBronzePacksFromStore', 4, 1),
                ('openPacks', None, 2),
                ('openUnTradablePacks', None, 2),
                ('openBronzePacksFromStore', 4, 2),
            ],
        )

    def test_бронза_без_числа_не_пишется(self):
        post = QueryDict(mutable=True)
        post.setlist('queue_slot', ['1'])
        post['queue_key_1'] = 'openPacks'
        post['mode_1_openPacks'] = '1'
        post['mode_1_openBronzePacksFromStore'] = '1'
        self.assertEqual(
            modes_from_post(post),
            [{'key': 'openPacks', 'value': None, 'slot': 1}],
        )

    def test_рынок_задания_и_разбор_в_очереди(self):
        state = editor_state([])
        session_keys = [item['key'] for item in state['session']]
        action_keys = [item['key'] for item in state['actions']]
        self.assertNotIn('checkMarketOpened', session_keys)
        self.assertNotIn('collectObjectives', session_keys)
        self.assertNotIn('handleUnsigned', session_keys)
        self.assertEqual(
            action_keys[:6],
            [
                'checkMarketOpened',
                'collectObjectives',
                'collectSBC',
                'openPacks',
                'openPreviewPack',
                'handleUnsigned',
            ],
        )

    def test_редактор_помнит_порядок_и_две_карточки_паков(self):
        state = editor_state([
            {'key': 'openPacks', 'value': None, 'slot': 1},
            {'key': 'openUnTradablePacks', 'value': None, 'slot': 1},
            {'key': 'openBronzePacksFromStore', 'value': 4, 'slot': 2},
            {'key': 'collectSBC', 'value': None, 'slot': 3},
        ])
        packs = [item for item in state['actions'] if item['key'] == 'openPacks']
        self.assertEqual(len(packs), 2)
        first_flags = [item['key'] for item in packs[0]['conditions'] if item['checked']]
        second_flags = [item['key'] for item in packs[1]['conditions'] if item['checked']]
        self.assertEqual(first_flags, ['openUnTradablePacks', 'openBronzePacksFromStore'])
        self.assertEqual(second_flags, first_flags)
        self.assertEqual(packs[0]['conditions'][-1]['value'], 4)
        self.assertEqual(packs[1]['conditions'][-1]['value'], 4)
        keys = [item['key'] for item in state['actions'] if item['checked']]
        self.assertEqual(keys, ['openPacks', 'openPacks', 'collectSBC'])

    def test_копии_сбч_делят_область_и_флаги(self):
        post = QueryDict(mutable=True)
        post.setlist('queue_slot', ['1', '2'])
        post['queue_key_1'] = 'collectSBC'
        post['queue_key_2'] = 'collectSBC'
        post['mode_1_collectSBC'] = '1'
        post['sbc_scope_1'] = 'priority'
        post['mode_1_useBronze200ForSbc'] = '1'
        post['mode_2_collectSBC'] = '1'
        post['sbc_scope_2'] = 'all'
        items = modes_from_post(post)
        self.assertEqual(
            [item['key'] for item in items],
            [
                'collectSBC',
                'collectAllSbc',
                'useBronze200ForSbc',
                'collectSBC',
                'collectAllSbc',
                'useBronze200ForSbc',
            ],
        )
        self.assertEqual([item['slot'] for item in items], [1, 1, 1, 2, 2, 2])

    def test_редактор_без_scope_ставит_все(self):
        state = editor_state([{'key': 'collectSBC', 'value': None}])
        self.assertEqual(state['sbc_scope'], 'all')
        titles = [item['title'] for item in state['scope_options']]
        self.assertEqual(
            titles,
            ['Собрать все сбч', 'Собрать сбч приоритет', 'Собрать сбч без приоритета'],
        )
