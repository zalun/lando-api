# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import json
import logging
import os
import pytest
import requests_mock

from moto import mock_s3
from sqlalchemy.exc import OperationalError

from landoapi.app import create_app
from landoapi.storage import db as _db
from tests.factories import PhabResponseFactory, TransResponseFactory


@pytest.fixture
def docker_env_vars(monkeypatch):
    """Monkeypatch environment variables that we'd get running under docker."""
    monkeypatch.setenv('PHABRICATOR_URL', 'http://phabricator.test')
    monkeypatch.setenv('TRANSPLANT_URL', 'http://autoland.test')
    #monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.setenv(
        'DATABASE_URL',
        'postgresql://postgres:password@postgres.pytest/postgres'
    )
    monkeypatch.setenv('TRANSPLANT_API_KEY', 'someapikey')
    monkeypatch.setenv('PINGBACK_ENABLED', 'y')
    monkeypatch.setenv('PINGBACK_HOST_URL', 'http://lando-api.test')
    monkeypatch.setenv('PATCH_BUCKET_NAME', 'landoapi.test.bucket')
    monkeypatch.setenv('AWS_ACCESS_KEY', None)
    monkeypatch.setenv('AWS_SECRET_KEY', None)


@pytest.fixture
def request_mocker():
    """Yield a requests Mocker for response factories."""
    with requests_mock.mock() as m:
        yield m


@pytest.fixture
def phabfactory(request_mocker):
    """Mock the Phabricator service and build fake response objects."""
    yield PhabResponseFactory(request_mocker)


@pytest.fixture
def transfactory(request_mocker):
    """Mock Transplant service."""
    yield TransResponseFactory(request_mocker)


@pytest.fixture
def versionfile(tmpdir):
    """Provide a temporary version.json on disk."""
    v = tmpdir.mkdir('app').join('version.json')
    v.write(
        json.dumps(
            {
                'source': 'https://github.com/mozilla-conduit/lando-api',
                'version': '0.0.0',
                'commit': '',
                'build': 'test',
            }
        )
    )
    return v


@pytest.fixture
def disable_migrations(monkeypatch):
    """Disable the Alembic DB migrations system in the app during testing."""

    class StubAlembic:
        def __init__(self):
            pass

        def init_app(self, app):
            pass

    monkeypatch.setattr('landoapi.app.alembic', StubAlembic())


@pytest.fixture
def disable_log_output():
    """Disable Python standard logging output to the console."""
    logging.disable(logging.CRITICAL)


@pytest.fixture
def app(versionfile, docker_env_vars, disable_migrations, disable_log_output):
    """Needed for pytest-flask."""
    app = create_app(versionfile.strpath)
    return app.app


@pytest.fixture
def db(app):
    """Reset database for each test."""
    with app.app_context():
        _db.init_app(app)
        # Skip if database is not available.
        try:
            _db.create_all()
        except OperationalError as exc:
            # Check if that's exactly the exception which needs to be skipped
            if 'Name does not resolve' not in str(exc):
                raise

            pytest.skip('Unable to initialize the database')

        yield _db
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def s3(app, docker_env_vars):
    """Provide s3 mocked connection."""
    bucket = os.getenv('PATCH_BUCKET_NAME')
    with app.app_context():
        with mock_s3():
            s3 = boto3.resource('s3')
            # We need to create the bucket since this is all in Moto's
            # 'virtual' AWS account
            s3.create_bucket(Bucket=bucket)
            yield s3
