import logging

import requests
from django.conf import settings


def auto_buy_chat_id():
    raw = (getattr(settings, 'TELEGRAM_CHATS', {}) or {}).get('auto_buy')
    if raw:
        return int(raw)
    return -1001656582679


def send_auto_buy(text, post=None):
    token = getattr(settings, 'TELEGRAM_TOKEN', '') or ''
    if not token:
        logging.info('Telegram auto buyer не отправлен: нет токена')
        return False
    sender = post or _post
    try:
        response = sender(token, auto_buy_chat_id(), text)
    except OSError:
        logging.info('Telegram auto buyer не отправлен: нет связи')
        return False
    code = getattr(response, 'status_code', 0)
    if code != 200:
        logging.info('Telegram auto buyer ответил %s', code)
        return False
    logging.info('Telegram auto buyer отправлен')
    return True


def _post(token, chat_id, text):
    proxies = None
    socks = getattr(settings, 'SOCKS', '') or ''
    if socks:
        proxies = {'http': socks, 'https': socks}
    return requests.post(
        'https://api.telegram.org/bot%s/sendMessage' % token,
        json={'chat_id': chat_id, 'text': text},
        proxies=proxies,
        timeout=(10, 30),
    )
