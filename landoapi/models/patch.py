# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import logging
import tempfile

from flask import current_app

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.phabricator_client import PhabricatorClient
from landoapi.storage import db

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = 's3://{bucket}/{patch_name}'


class Patch(db.Model):
    """Represents patches uploaded to S3 and provided for landing.

    Columns:
        id: PK
        landing_id: Id of the Landing in LandoAPI
        parent_id: Id of the parent Patch
        revision_id: Id of the revision in Phabricator
        diff_id: Id of the diff in Phabricator
        s3_url: A URL in PATCH_URL_FORMAT

    Relations:
        Patch is created in a landing process. Many patches might be related
        to a Landing.
        Some revisions are stacked and parent represents the patch which needs
        to be landed before the current one. If revision is related
        directly to master patch will have no parent.
    """
    __tablename__ = "patches"

    id = db.Column(db.Integer, primary_key=True)
    landing_id = db.Column(db.Integer, db.ForeignKey('landings.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('patches.id'))
    revision_id = db.Column(db.Integer)
    diff_id = db.Column(db.Integer)
    s3_url = db.Column(db.String(128))
    child = db.relationship('Patch', uselist='false')

    def __init__(
        self, landing_id, revision, diff_id, parent_id=None, s3_url=None
    ):
        """Create a patch instance.

        Args:
            landing_id: id of the Landing
            revision: The revision as defined by Phabricator API
            diff_id: The id of the diff to be landed
            parent_id: Id of the parent Patch
        """
        self.landing_id = landing_id
        self.parent_id = parent_id
        self.revision_id = revision['id']
        self.diff_id = diff_id
        self.s3_url = s3_url
        # store revision for `upload`
        self.revision = revision

    def upload(self, phabricator_api_key=None):
        """Upload patch to S3

        Args:
            phabricator_api_key: API Key to identify in Phabricator

        Request diff and revision author from Phabricator API.
        Build the patch contents and upload to S3.
        """
        phab = PhabricatorClient(phabricator_api_key)
        diff = phab.get_rawdiff(self.diff_id)

        if not diff:
            raise DiffNotFoundException(self.diff_id)

        author = phab.get_revision_author(self.revision)
        hgpatch = build_patch_for_revision(diff, author, self.revision)

        # Upload patch to S3.
        self.s3_url = _upload_patch_to_s3(
            hgpatch, self.landing_id, self.revision_id, self.diff_id
        )

        logger.info(
            {
                'patch_url': self.s3_url,
                'msg': 'Patch file uploaded'
            }, 'landing.patch_uploaded'
        )
        return self

    def save(self):
        """ Save objects in storage. """
        if not self.id:
            db.session.add(self)

        db.session.commit()
        return self


class DiffNotFoundException(Exception):
    """ Phabricator returned 404 for a given diff id. """

    def __init__(self, diff_id):
        super().__init__()
        self.diff_id = diff_id


def _upload_patch_to_s3(patch, landing_id, revision_id, diff_id):
    """Save patch in S3 bucket.

    Creates a temporary file and uploads it to an S3 bucket.

    Args:
        patch: Text to be saved
        landing_id: Id of the landing in Lando API
        revision_id: String ID of the revision (ex. 'D123')
        diff_id: The integer ID of the raw diff

    Returns
        String representing the patch's URL in S3
        (ex. 's3://{bucket_name}/L34_D123_567.patch')
    """
    s3 = boto3.resource(
        's3',
        aws_access_key_id=current_app.config['AWS_ACCESS_KEY'],
        aws_secret_access_key=current_app.config['AWS_SECRET_KEY']
    )
    patch_name = 'L{landing_id}_D{revision_id}_{diff_id}.patch'.format(
        landing_id=landing_id, revision_id=revision_id, diff_id=diff_id
    )
    bucket = current_app.config['PATCH_BUCKET_NAME']
    patch_url = PATCH_URL_FORMAT.format(bucket=bucket, patch_name=patch_name)
    with tempfile.TemporaryFile() as patchfile:
        patchfile.write(patch.encode('utf-8'))
        patchfile.seek(0)
        s3.meta.client.upload_fileobj(patchfile, bucket, patch_name)

    return patch_url
