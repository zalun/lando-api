# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
import requests_mock

from landoapi.api.revisions import _build_reviewers
from landoapi.phabricator_client import PhabricatorClient
from landoapi.utils import format_commit_message_title
from tests.canned_responses.lando_api.revisions import (
    CANNED_LANDO_REVISION_1, CANNED_LANDO_REVISION_2,
    CANNED_LANDO_REVIEWERS_PARTIAL, CANNED_LANDO_REVISION_NOT_FOUND,
    CANNED_REVIEWERS_USER_DONT_MATCH_PARTIAL
)
from tests.canned_responses.phabricator.revisions import (
    CANNED_REVISION_2, CANNED_REVISION_2_REVIEWERS,
    CANNED_TWO_REVIEWERS_SEARCH_RESPONSE
)
from tests.canned_responses.phabricator.users import CANNED_USER_SEARCH_1
from tests.utils import phab_url, phid_for_response

pytestmark = pytest.mark.usefixtures('docker_env_vars')


def test_get_revision(client, phabfactory):
    phabfactory.revision()
    response = client.get('/revisions/D1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json == CANNED_LANDO_REVISION_1


def test_get_revision_with_no_parents(client, phabfactory):
    phabfactory.revision(depends_on=[])
    response = client.get('/revisions/D1')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert response.json['parent_revisions'] == []


def test_get_revision_with_parents(client, phabfactory):
    rev1 = phabfactory.revision(id='D1')
    phabfactory.revision(id='D2', template=CANNED_REVISION_2, depends_on=rev1)
    response = client.get('/revisions/D2')
    assert response.status_code == 200
    assert response.content_type == 'application/json'
    assert len(response.json['parent_revisions']) == 1
    parent_revision = response.json['parent_revisions'][0]
    assert parent_revision['phid'] == phid_for_response(rev1)
    assert response.json == CANNED_LANDO_REVISION_2


def test_get_revision_returns_404(client, phabfactory):
    response = client.get('/revisions/D9000')
    assert response.status_code == 404
    assert response.content_type == 'application/problem+json'
    assert response.json == CANNED_LANDO_REVISION_NOT_FOUND


def test_get_revision_no_reviewers(client, phabfactory):
    phabfactory.revision(reviewers=[])
    response = client.get('/revisions/D1')
    assert response.status_code == 200
    assert response.json['reviewers'] == []


def test_get_revision_multiple_reviewers(client, phabfactory):
    phabfactory.revision(
        reviewers=[
            {
                'id': 2,
                'username': 'foo'
            }, {
                'id': 3,
                'username': 'bar',
                'status': 'rejected',
                'isBlocking': True,
                'phid': 'PHID-USER-forced-in-test'
            }
        ]
    )
    response = client.get('/revisions/D1')
    assert response.status_code == 200
    assert response.json['reviewers'] == CANNED_LANDO_REVIEWERS_PARTIAL


def test_build_reviewers_reviewers_and_users_dont_match():
    phab = PhabricatorClient(api_key=None)
    with requests_mock.mock() as m:
        m.get(
            phab_url('differential.query'),
            status_code=200,
            json=CANNED_REVISION_2_REVIEWERS
        )
        m.get(
            phab_url('differential.revision.search'),
            status_code=200,
            json=CANNED_TWO_REVIEWERS_SEARCH_RESPONSE
        )
        m.get(
            phab_url('user.search'),
            status_code=200,
            json=CANNED_USER_SEARCH_1
        )
        reviewers = _build_reviewers(phab, 1)

    assert reviewers == CANNED_REVIEWERS_USER_DONT_MATCH_PARTIAL


def test_commit_message_for_multiple_reviewers():
    reviewers = ['reviewer_one', 'reviewer_two']
    commit_message = format_commit_message_title('A title.', 1, reviewers)
    assert commit_message == 'Bug 1 - A title. r=reviewer_one,r=reviewer_two'
