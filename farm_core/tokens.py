import hashlib
import hmac


def hash_token(token):
    return hashlib.sha256((token or '').encode('utf-8')).hexdigest()


def token_matches(stored_hash, token):
    if not stored_hash or not token:
        return False
    return hmac.compare_digest(stored_hash, hash_token(token))
