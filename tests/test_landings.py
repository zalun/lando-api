# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os
import pytest

from unittest.mock import MagicMock

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.models.landing import Landing, TRANSPLANT_JOB_LANDED
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

from tests.canned_responses.lando_api.revisions import *
from tests.canned_responses.lando_api.landings import *


def test_landing_revision_saves_data_in_db(
    db, client, phabfactory, transfactory, s3
):
    # Id of the landing in Autoland is created as a result of a POST request to
    # /autoland endpoint. It is provided by Transplant API
    land_request_id = 3
    # Id of a Landing object is created as a result of a POST request to
    # /landings endpoint of Lando API
    landing_id = 1
    # Id of the diff existing in Phabricator
    diff_id = 2

    phabfactory.user()
    phabfactory.revision()
    phabfactory.rawdiff(diff_id)
    transfactory.create_autoland_response(land_request_id)

    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': diff_id
        }),
        content_type='application/json'
    )
    assert response.status_code == 202
    assert response.content_type == 'application/json'
    # Id of the Landing object in Lando API
    assert response.json == {'id': landing_id}

    # Get Landing object by its id
    landing = Landing.query.get(landing_id)
    landing.request_id = land_request_id
    assert landing.serialize() == CANNED_LANDING_FACTORY_1


def test_landing_stacked_revisions(db, client, phabfactory, transfactory, s3):
    phabfactory.user()
    d1 = phabfactory.diff()
    d2 = phabfactory.diff(id=2)
    d3 = phabfactory.diff(id=3)
    # Stacked revisions - r3 depends on r2 which depends on r1
    # r3 -- r2 -- r1
    r1 = phabfactory.revision(id='D1', active_diff=d1)
    r2 = phabfactory.revision(id='D2', active_diff=d2, depends_on=[r1])
    phabfactory.revision(id='D3', active_diff=d3, depends_on=[r2])
    transfactory.create_autoland_response(1)

    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D3',
            'diff_id': 3
        }),
        content_type='application/json'
    )

    assert response.status_code == 202

    response = client.get('/landings/1')
    assert response.json['patch_urls'] == [
        's3://landoapi.test.bucket/L1_D1_1.patch',
        's3://landoapi.test.bucket/L1_D2_2.patch',
        's3://landoapi.test.bucket/L1_D3_3.patch'
    ]


def test_preventing_multiple_parents(
    db, client, phabfactory, transfactory, s3
):
    phabfactory.user()
    d1 = phabfactory.diff()
    d2 = phabfactory.diff(id=2)
    d3 = phabfactory.diff(id=3)
    d4 = phabfactory.diff(id=4)
    # Multiple parents dependency can't be landed, but is allowed
    # in Phabricator
    #
    # r4 -- r3 -- r1
    #         '-- r2
    #
    # r4 depends on r3 which depends on r1 and r2
    r1 = phabfactory.revision(id='D1', active_diff=d1)
    r2 = phabfactory.revision(id='D2', active_diff=d2)
    r3 = phabfactory.revision(id='D3', active_diff=d3, depends_on=[r1, r2])
    phabfactory.revision(id='D4', active_diff=d4, depends_on=[r3])
    transfactory.create_autoland_response(1)

    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D4',
            'diff_id': 4
        }),
        content_type='application/json'
    )

    assert response.status_code == 400
    assert response.json['title'] == 'Multiple parent revisions detected'
    assert response.json['detail'].startswith('Revision 3 has multiple')


def test_landing_revision_calls_transplant_service(
    db, client, phabfactory, monkeypatch, s3
):
    # Mock the phabricator response data
    phabfactory.user()
    phabfactory.revision()

    # Build the patch we expect to see
    phabclient = PhabricatorClient('someapi')
    revision = phabclient.get_revision('D1')
    diff_id = phabclient.get_diff(phid=revision['activeDiffPHID'])['id']
    gitdiff = phabclient.get_rawdiff(diff_id)
    author = phabclient.get_revision_author(revision)
    hgpatch = build_patch_for_revision(gitdiff, author, revision)
    patch_url = 's3://landoapi.test.bucket/L1_D1_1.patch'

    # The repo we expect to see
    repo_uri = phabclient.get_revision_repo(revision)['uri']

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr('landoapi.models.landing.TransplantClient', tsclient)
    client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': int(diff_id)
        }),
        content_type='application/json'
    )
    tsclient().land.assert_called_once_with(
        'ldap_username@example.com', [patch_url], repo_uri,
        '{}/landings/1/update'.format(os.getenv('PINGBACK_HOST_URL'))
    )
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == hgpatch


def test_get_transplant_status(db, client):
    Landing(1, 'D1', 1, 'started').save()
    response = client.get('/landings/1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDING_1


def test_land_nonexisting_revision_returns_404(db, client, phabfactory, s3):
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D900',
            'diff_id': 1
        }),
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def test_land_nonexisting_diff_returns_404(db, client, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()
    phabfactory.rawdiff(1)
    response = client.post(
        '/landings?api_key=api-key',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 9000
        }),
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_DIFF_NOT_FOUND


def test_get_jobs(db, client):
    Landing(1, 'D1', 1, 'started').save()
    Landing(2, 'D1', 2, 'finished').save()
    Landing(3, 'D2', 3, 'started').save()
    Landing(4, 'D1', 4, 'started').save()
    Landing(5, 'D2', 5, 'finished').save()

    response = client.get('/landings')
    assert response.status_code == 200
    assert len(response.json) == 5

    response = client.get('/landings?revision_id=D1')
    assert response.status_code == 200
    assert len(response.json) == 3
    assert response.json == CANNED_LANDING_LIST_1

    response = client.get('/landings?status=finished')
    assert response.status_code == 200
    assert len(response.json) == 2

    response = client.get('/landings?revision_id=D1&status=finished')
    assert response.status_code == 200
    assert len(response.json) == 1


def test_update_landing(db, client):
    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 202
    response = client.get('/landings/1')
    assert response.json['status'] == TRANSPLANT_JOB_LANDED


def test_update_landing_bad_id(db, client):
    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/2/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 404


def test_update_landing_bad_request_id(db, client):
    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 2,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 404


def test_update_landing_bad_api_key(db, client):
    Landing(1, 'D1', 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'wrongapikey')],
        content_type='application/json'
    )

    assert response.status_code == 403


def test_update_landing_no_api_key(db, client):
    Landing(1, 'D1', 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        content_type='application/json'
    )

    assert response.status_code == 400


def test_pingback_disabled(db, client, monkeypatch):
    monkeypatch.setenv('PINGBACK_ENABLED', 'n')

    Landing(1, 'D1', 1, 'started').save()

    response = client.post(
        '/landings/1/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 403
