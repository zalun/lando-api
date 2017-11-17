# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import json
import os

from freezegun import freeze_time
from unittest.mock import MagicMock

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.models.landing import Landing, TRANSPLANT_JOB_LANDED
from landoapi.phabricator_client import PhabricatorClient
from landoapi.transplant_client import TransplantClient

from tests.canned_responses.auth0 import CANNED_USERINFO
from tests.canned_responses.lando_api.revisions import (
    CANNED_LANDO_DIFF_NOT_FOUND,
    CANNED_LANDO_REVISION_NOT_FOUND,
)
from tests.canned_responses.lando_api.landings import (
    CANNED_LANDING_1,
    CANNED_LANDING_FACTORY_1,
    CANNED_LANDING_LIST_1,
)
from tests.utils import phab_url, form_matcher


@freeze_time('2017-11-02T00:00:00')
def test_landing_revision_saves_data_in_db(
    db, client, phabfactory, transfactory, s3, auth0_mock
):
    # Id of the landing in Autoland is created as a result of a POST request to
    # /autoland endpoint. It is provided by Transplant API
    land_request_id = 3
    # Id of a Landing object is created as a result of a POST request to
    # /landings endpoint of Lando API
    landing_id = 1
    # Id of the diff existing in Phabricator
    diff_id = 2

    diff = phabfactory.diff(id=diff_id)
    phabfactory.revision(active_diff=diff)
    transfactory.create_autoland_response(land_request_id)

    response = client.post(
        '/landings',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': diff_id
        }),
        headers=auth0_mock.mock_headers,
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


def test_landing_without_auth0_permissions(
    db, client, phabfactory, transfactory, s3, auth0_mock
):
    auth0_mock.userinfo = CANNED_USERINFO['NO_CUSTOM_CLAIMS']

    response = client.post(
        '/landings',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 1,
        }),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 403


def test_landing_revision_calls_transplant_service(
    db, client, phabfactory, monkeypatch, s3, auth0_mock
):
    # Mock the phabricator response data
    phabfactory.revision()

    # Build the patch we expect to see
    phabclient = PhabricatorClient('someapi')
    revision = phabclient.get_revision(1)
    diff_id = phabclient.get_diff(phid=revision['activeDiffPHID'])['id']
    gitdiff = phabclient.get_rawdiff(diff_id)
    author = phabclient.get_revision_author(revision)
    hgpatch = build_patch_for_revision(gitdiff, author, revision)
    patch_url = 's3://landoapi.test.bucket/L1_D1_1.patch'

    tsclient = MagicMock(spec=TransplantClient)
    tsclient().land.return_value = 1
    monkeypatch.setattr('landoapi.models.landing.TransplantClient', tsclient)
    client.post(
        '/landings',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': int(diff_id)
        }),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    tsclient().land.assert_called_once_with(
        ldap_username='land_requester_ldap_email@example.com',
        patch_urls=[patch_url],
        tree='mozilla-central',
        pingback='{}/landings/update'.format(os.getenv('PINGBACK_HOST_URL'))
    )
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == hgpatch


@freeze_time('2017-11-02T00:00:00')
def test_get_transplant_status(db, client):
    _create_landing(1, 1, 1, status='started')
    response = client.get('/landings/1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDING_1


def test_land_nonexisting_revision_returns_404(
    client, phabfactory, s3, auth0_mock
):
    response = client.post(
        '/landings',
        data=json.dumps({
            'revision_id': 'D900',
            'diff_id': 1
        }),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def test_land_nonexisting_diff_returns_404(
    db, client, phabfactory, auth0_mock
):
    # This shouldn't really happen - it would be a bug in Phabricator.
    # There is a repository which active diff does not exist.
    diff = {
        'id': '9000',
        'uri': '{url}/differential/diff/9000/'.format(
            url=os.getenv('PHABRICATOR_URL')
        )
    }  # yapf: disable
    phabfactory.revision(active_diff={'result': {'9000': diff}})
    phabfactory.mock.get(
        phab_url('phid.query'),
        status_code=404,
        additional_matcher=form_matcher('phids[]', 'PHID-DIFF-9000'),
        json={
            'error_info': '',
            'error_code': None,
            'result': {
                'PHID-DIFF-9000': diff
            }
        }
    )

    response = client.post(
        '/landings',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 9000
        }),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_DIFF_NOT_FOUND


def test_land_inactive_diff_returns_409(
    db, client, phabfactory, transfactory, auth0_mock
):
    phabfactory.diff(id=1)
    d2 = phabfactory.diff(id=2)
    phabfactory.revision(active_diff=d2)
    transfactory.create_autoland_response()
    response = client.post(
        '/landings',
        data=json.dumps({
            'revision_id': 'D1',
            'diff_id': 1
        }),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 409
    assert response.content_type == 'application/problem+json'
    assert response.json['title'] == 'Inactive Diff'


def test_override_inactive_diff(
    db, client, phabfactory, transfactory, auth0_mock
):
    phabfactory.diff(id=1)
    phabfactory.diff(id=2)
    d3 = phabfactory.diff(id=3)
    phabfactory.revision(active_diff=d3)
    transfactory.create_autoland_response()
    response = client.post(
        '/landings',
        data=json.dumps(
            {
                'revision_id': 'D1',
                'diff_id': 1,
                'force_override_of_diff_id': 2
            }
        ),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 409
    assert response.content_type == 'application/problem+json'
    assert response.json['title'] == 'Overriding inactive diff'


def test_override_active_diff(
    db, client, phabfactory, transfactory, s3, auth0_mock
):
    phabfactory.diff(id=1)
    d2 = phabfactory.diff(id=2)
    phabfactory.revision(active_diff=d2)
    transfactory.create_autoland_response()
    response = client.post(
        '/landings',
        data=json.dumps(
            {
                'revision_id': 'D1',
                'diff_id': 1,
                'force_override_of_diff_id': 2
            }
        ),
        headers=auth0_mock.mock_headers,
        content_type='application/json'
    )
    assert response.status_code == 202

    landing = Landing.query.get(1)
    assert landing.status == 'started'
    assert landing.active_diff_id == 2
    assert landing.diff_id == 1


@freeze_time('2017-11-02T00:00:00')
def test_get_jobs(db, client):
    _create_landing(1, 1, 1, status='started')
    _create_landing(2, 1, 2, status='finished')
    _create_landing(3, 2, 3, status='started')
    _create_landing(4, 1, 4, status='started')
    _create_landing(5, 2, 5, status='finished')

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
    _create_landing(1, 1, 1, status='started')

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 200
    response = client.get('/landings/1')
    assert response.json['status'] == TRANSPLANT_JOB_LANDED


def test_update_landing_bad_request_id(db, client):
    _create_landing(1, 1, 1, status='started')

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 2,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 404


def test_update_landing_bad_api_key(client):
    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'wrongapikey')],
        content_type='application/json'
    )

    assert response.status_code == 403


def test_update_landing_no_api_key(client):
    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        content_type='application/json'
    )

    assert response.status_code == 400


def test_pingback_disabled(client, monkeypatch):
    monkeypatch.setenv('PINGBACK_ENABLED', 'n')

    response = client.post(
        '/landings/update',
        data=json.dumps({
            'request_id': 1,
            'landed': True,
            'result': 'sha123'
        }),
        headers=[('API-Key', 'someapikey')],
        content_type='application/json'
    )

    assert response.status_code == 403


def _create_landing(
    request_id=1,
    revision_id='D1',
    diff_id=1,
    active_diff_id=None,
    requester_email='land_requester_ldap_email@example.com',
    tree='mozilla-central',
    status='started'
):
    landing = Landing(
        request_id=request_id,
        revision_id=revision_id,
        diff_id=diff_id,
        active_diff_id=(active_diff_id or diff_id),
        requester_email=requester_email,
        tree=tree,
        status=status
    )
    landing.save()
    return landing
