# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import pytest

from landoapi.models.patch import DiffNotInRevisionException, Patch
from landoapi.phabricator_client import PhabricatorClient


def test_patch_uploads_to_s3(db, phabfactory, s3):
    phabfactory.revision()
    phabfactory.rawdiff(1)

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1)
    expected_body = patch.build(phab)
    patch.upload(phab)

    assert patch.s3_url == 's3://landoapi.test.bucket/L1_D1_1.patch'
    body = s3.Object('landoapi.test.bucket',
                     'L1_D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == expected_body


def test_integrity(phabfactory):
    phabfactory.revision()
    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1)
    assert patch.check_integrity(phab) is None


def test_failed_integrity(phabfactory):
    diff_id = 500
    phabfactory.revision()
    phabfactory.diff(id=diff_id, revision_id='D123')
    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, diff_id)
    with pytest.raises(DiffNotInRevisionException):
        patch.check_integrity(phab)
