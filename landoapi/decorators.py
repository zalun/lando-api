# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import functools

from connexion import (
    problem,
    request,
)
from flask import current_app, g

from landoapi.phabricator import PhabricatorClient


class require_phabricator_api_key:
    """Decorator which requires and verifies the phabricator API Key.

    Using this decorator on a connexion handler will require a phabricator
    api key be sent in the `X-Phabricator-API-Key` header of the request. If
    the header is not provided an HTTP 401 response will be sent.

    The provided API key will be verified to be valid, if it is not an
    HTTP 403 response will be sent.

    If the optional parameter is True and no API key is provided, a default key
    will be used. If an API key is provided it will still be verified.

    Decorated functions may assume X-Phabricator-API-Key header is present,
    contains a valid phabricator API key and flask.g.phabricator is a
    PhabricatorClient using this API Key.
    """

    def __init__(self, optional=False):
        self.optional = optional

    def __call__(self, f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            api_key = request.headers.get('X-Phabricator-API-Key')

            if api_key is None and not self.optional:
                return problem(
                    401,
                    'X-Phabricator-API-Key Required',
                    ('Phabricator api key not provided in '
                     'X-Phabricator-API-Key header'),
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/401'  # noqa: E501
                )  # yapf: disable

            g.phabricator = PhabricatorClient(
                current_app.config['PHABRICATOR_URL'], api_key or
                current_app.config['PHABRICATOR_UNPRIVILEGED_API_KEY']
            )
            if api_key is not None and not g.phabricator.verify_api_token():
                return problem(
                    403,
                    'X-Phabricator-API-Key Invalid',
                    'Phabricator api key is not valid',
                    type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403'  # noqa: E501
                )  # yapf: disable

            return f(*args, **kwargs)

        return wrapped


class LazyValue:
    def __init__(self, f, args, kwargs):
        self._args = args
        self._kwargs = kwargs
        self._value = None
        self._cached = False
        self._f = f

    def __call__(self):
        if not self._cached:
            args = [
                (arg() if isinstance(arg, LazyValue) else arg)
                for arg in self._args
            ]
            kwargs = {
                k: (v() if isinstance(v, LazyValue) else v)
                for k, v in self._kwargs.items()
            }
            self._value = self._f(*args, **kwargs)
            self._cached = True

        return self._value


class lazy:
    """Decorator which allows for "lazy evaluation".

    This decorator will chain with any LazyValues it is passed as arguments
    to its __call__ method. This means if a LazyValue generated from another
    lazy function is passed as an argument, it will be evaluated and the result
    will be passed to the underlying function, rather than the LazyValue
    itself.

    Chaining the LazyValues allows for building lazy chains which depend on
    functions which weren't explicitly written to be lazy. For example, if we'd
    like to make a pre-existing function lazy and that function takes data
    generated by another function, we might not want to call the data
    generating function if/until we call the new lazy function. This can be
    achieved by wrapping the data generating function and passing as a
    LazyValue, which will be automatically executed when the first lazy is
    evaluated.

    This does mean that something like the following example is impossible:
        ```
        @lazy
        func1(get_lazy_value):
          value = get_lazy_value()
        ```
    `get_lazy_value` above will be executed before being passed to func1. To
    work around this you can wrap the LazyValue in another structure, such
    as a dict or tuple.
    """

    def __init__(self, f):
        self._f = f

    def __call__(self, *args, **kwargs):
        return functools.wraps(self._f)(LazyValue(self._f, args, kwargs))
