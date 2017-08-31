# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable
import pytest

from landoapi.models.patch import Patch
from landoapi.models.landing import Landing
from landoapi.phabricator_client import PhabricatorClient

from tests.canned_responses.lando_api.patches import CANNED_PATCH_1

def test_patch_uploads_to_s3(db, phabfactory, s3):
    phabfactory.user()
    phabfactory.revision()
    phabfactory.rawdiff(1)

    phab = PhabricatorClient(None)
    revision = phab.get_revision(1)
    patch = Patch(1, revision, 1).upload()

    assert patch.s3_url == 's3://landoapi.test.bucket/D1_1.patch'
    body = s3.Object('landoapi.test.bucket', 'D1_1.patch').get()['Body'].read().decode("utf-8")
    assert body == CANNED_PATCH_1
