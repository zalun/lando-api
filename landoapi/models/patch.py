# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import datetime
import logging
import tempfile

from flask import current_app

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.storage import db
from landoapi.utils import revision_id_to_int

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = 's3://{bucket}/{patch_name}'
PATCH_NAME_FORMAT = 'L{landing_id}_D{revision_id}_{diff_id}.patch'


class Patch(db.Model):
    """Represents patches uploaded to S3 and provided for landing.

    Patch is created in a landing process. Many patches might be related
    to a Landing.
    Some revisions are stacked and parent_id represents the patch which needs
    to be landed before the current one. If revision is related directly to
    a master, patch will have no parent and parent_id will be None.

    Attributes:
        id: PK
        landing_id: Id of the Landing in LandoAPI
        revision_id: Id of the revision in Phabricator
        diff_id: Id of the diff in Phabricator
        s3_url: A URL in PATCH_URL_FORMAT
        created: DateTime of creation of the Patch object
    """
    __tablename__ = "patches"

    id = db.Column(db.Integer, primary_key=True)
    landing_id = db.Column(db.Integer, db.ForeignKey('landings.id'))
    revision_id = db.Column(db.Integer)
    diff_id = db.Column(db.Integer)
    s3_url = db.Column(db.String(128))
    created = db.Column(db.DateTime())

    def __init__(
        self, landing_id, revision, diff_id, s3_url=None, phabricator=None
    ):
        """Create a patch instance.

        Args:
            landing_id: id of the Landing
            revision: The revision as defined by Phabricator API
            diff_id: The id of the diff to be landed
            phabricator: PhabricatorClient instance
        """
        self.landing_id = int(landing_id)
        self.revision_id = revision_id_to_int(revision['id'])
        self.diff_id = int(diff_id)
        self.created = datetime.datetime.utcnow()
        # store revision and phabricator client for build
        self._revision = revision
        self._phabricator = phabricator

    def build(self):
        """Build the patch contents using diff.

        Request diff and revision author from Phabricator API and build the
        patch using the result.

        Returns:
            A string containing a patch in 'hg export' format.

        Raises:
            DiffNotFoundException: PhabricatorClient returned no diff for
                given diff_id
        """
        diff = self._phabricator.get_rawdiff(self.diff_id)

        if not diff:
            raise DiffNotFoundException(self.diff_id)

        author = self._phabricator.get_revision_author(self._revision)
        return build_patch_for_revision(diff, author, self._revision)

    def upload(self):
        """Upload the patch to S3 Bucket.

        Build the patch contents and upload to S3.
        """
        hgpatch = self.build()

        # Upload patch to S3.
        s3 = boto3.resource(
            's3',
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY'],
            aws_secret_access_key=current_app.config['AWS_SECRET_KEY']
        )
        patch_name = PATCH_NAME_FORMAT.format(
            landing_id=self.landing_id,
            revision_id=self._revision['id'],
            diff_id=self.diff_id
        )
        bucket = current_app.config['PATCH_BUCKET_NAME']
        self.s3_url = PATCH_URL_FORMAT.format(
            bucket=bucket, patch_name=patch_name
        )

        with tempfile.TemporaryFile() as patchfile:
            patchfile.write(hgpatch.encode('utf-8'))
            patchfile.seek(0)
            s3.meta.client.upload_fileobj(patchfile, bucket, patch_name)

        logger.info(
            {
                'patch_url': self.s3_url,
                'msg': 'Patch file uploaded'
            }, 'landing.patch_uploaded'
        )

    def save(self):
        """Save object to db."""
        if not self.id:
            db.session.add(self)

        return db.session.commit()


class DiffNotFoundException(Exception):
    """Phabricator returned 404 for a given diff id."""

    def __init__(self, diff_id):
        super().__init__()
        self.diff_id = diff_id
