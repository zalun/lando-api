# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Test save patch in db and upload to S3 bucket."""
import pytest

from freezegun import freeze_time

from landoapi.models.patch import Patch
from landoapi.phabricator_client import PhabricatorClient


@freeze_time('2017-09-12T00:00:00.1')
def test_patch_is_saved_in_db(db, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    Patch(revision, 1, 1).save()

    patch = Patch.query.get(1)
    assert patch.landing_id == 1
    assert patch.revision_id == 1
    assert patch.diff_id == 1
    assert patch.s3_url is None
    assert patch.created.isoformat() == '2017-09-12T00:00:00.100000'


@freeze_time('2017-09-12T00')
def test_patch_uploads_to_s3(db, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(revision, 1, 1, phabricator=phab)
    expected_body = patch.build()
    patch.upload()

    assert patch.s3_url == 's3://landoapi.test.bucket/D1_1_1505174400.patch'
    body = s3.Object('landoapi.test.bucket', 'D1_1_1505174400.patch'
                    ).get()['Body'].read().decode("utf-8")
    assert body == expected_body
