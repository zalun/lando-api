# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Construct an application instance that can be referenced by a WSGI server.
"""
import os

from .app import create_app

app = create_app(
    version_path=os.getenv('VERSION_PATH', '/app/version.json'),
    database_url=os.getenv('DATABASE_URL', 'sqlite://'),
    sentry_dsn=os.getenv('SENTRY_DSN', None),
    sentry_env=os.getenv('ENV', None)
)
