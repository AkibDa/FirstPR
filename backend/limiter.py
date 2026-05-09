import hashlib
from fastapi import Request
from slowapi import Limiter


def rate_limit_key(request: Request):
    """
    Generate a rate limiting key.
    Uses Authorization token when available,
    otherwise falls back to IP address.
    """

    auth_header = (
        request.headers.get("authorization")
        or request.headers.get("x-api-key")
    )

    if auth_header:
        token_hash = hashlib.sha256(
            auth_header.encode()
        ).hexdigest()

        return f"user:{token_hash}"

    forwarded = request.headers.get("x-forwarded-for")

    if forwarded:
        return f"ip:{forwarded.split(',')[0].strip()}"

    return f"ip:{request.client.host}"


limiter = Limiter(key_func=rate_limit_key)