import logging


def log_event(text):
    logging.getLogger('farm_journal').info(text)
