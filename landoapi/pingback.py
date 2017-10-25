# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Check if pingback is secure.
"""
import functools
import hmac
import logging
import os

from connexion import ProblemException, request

logger = logging.getLogger(__name__)
TRANSPLANT_API_KEY = os.getenv('TRANSPLANT_API_KEY')


def require_pingback_enabled(f):
    """Decorator which verifies if pingback is enabled.

    We allow the pingback requests only on specific containers.
    A container needs to have a PINGBACK_ENABLED environment variable is set
    to 'y'.
    """

    @functools.wraps(f)
    def wrapped(*args, **kwargs):

        if os.getenv('PINGBACK_ENABLED', 'n') != 'y':
            logger.warning(
                {
                    'remote_addr': request.remote_addr,
                    'msg': 'Attempt to access a disabled pingback',
                }, 'pingback.warning'
            )
            raise ProblemException(
                403,
                'Not Authorized',
                'Pingback is not enabled on this system',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403' # noqa
            ) #yapf: disable

        return f(*args, **kwargs)

    return wrapped


def require_transplant_api_key(f):
    """Decorator which verifies the Transplant API key."""

    @functools.wraps(f)
    def wrapped(*args, **kwargs):

        api_key = request.headers.get('API-Key')

        if api_key is None:
            raise ProblemException(
                401,
                'API-Key required',
                'Transplant api key not provided in API-Key header',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401' # noqa
            ) #yapf: disable

        if not hmac.compare_digest(api_key, TRANSPLANT_API_KEY):
            logger.warning(
                {
                    'remote_addr': request.remote_addr,
                    'msg': 'Wrong API Key',
                }, 'pingback.error'
            )
            raise ProblemException(
                403,
                'API-Key required',
                'Transplant api key not provided in API-Key header',
                type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403' # noqa
            ) #yapf: disable

        return f(*args, **kwargs)

    return wrapped
