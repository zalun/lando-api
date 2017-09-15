# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from freezegun import freeze_time

from landoapi.models.patch import Patch
from landoapi.models.landing import Landing
from landoapi.phabricator_client import PhabricatorClient

from tests.canned_responses.lando_api.patches import CANNED_PATCH_1


@freeze_time('2017-09-12T00:00:00.1')
def test_patch_is_saved_in_db(db, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    Patch(1, revision, 1).save()

    patch = Patch.query.get(1)
    assert patch.landing_id == 1
    assert patch.revision_id == 1
    assert patch.diff_id == 1
    assert patch.s3_url is None
    assert patch.created.isoformat() == '2017-09-12T00:00:00.100000'


def test_patch_uploads_to_s3(db, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1, phabricator=phab)
    expected_body = patch.build()
    patch.upload()

    assert patch.s3_url == 's3://landoapi.test.bucket/L1_D1_1.patch'
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == expected_body


def test_force_s3_url(db, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1, phabricator=phab)
    expected_body = patch.build()
    patch.upload()

    assert patch.s3_url == 's3://landoapi.test.bucket/L1_D1_1.patch'
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == expected_body
