# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Patch model representing a patch sent to Transplant."""
import datetime
import logging
import tempfile

import boto3
from flask import current_app

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.storage import db
from landoapi.phabricator_client import revision_id_to_int

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = 's3://{bucket}/{patch_name}'
PATCH_NAME_FORMAT = 'D{revision_id}_{diff_id}_{timestamp}.patch'


class Patch(db.Model):
    """Represents patches uploaded to S3 and provided for landing.

    Patch is created in a landing process.

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

    __phabricator = None

    def __init__(self, revision, diff_id, landing_id=None, phabricator=None):
        """Create a patch instance.

        Args:
            landing_id: id of the Landing
            revision: The revision as defined by Phabricator API
            diff_id: The id of the diff to be landed
            phabricator: PhabricatorClient instance
        """
        self.landing_id = landing_id
        self.revision_id = revision_id_to_int(revision['id'])
        self.diff_id = diff_id
        self.created = datetime.datetime.utcnow()
        # store revision and phabricator client for build
        self.__revision = revision
        self.__phabricator = phabricator

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
        diff = self.__phabricator.get_rawdiff(self.diff_id)

        if not diff:
            raise DiffNotFoundException(self.diff_id)

        author = self.__phabricator.get_revision_author(self.__revision)
        return build_patch_for_revision(diff, author, self.__revision)

    def upload(self):
        """Upload the patch to S3 Bucket.

        Build the patch contents and upload to S3.
        """
        hgpatch = self.build()
        # Upload patch to S3.
        # AWS credentials need to be set only for the development of Lando API.
        # This allows developers to save patch in a private bucket.
        # AWS_ACCESS_KEY and AWS_SECRET_KEY need to be left unconfigured
        # in production servers.
        s3 = boto3.resource(
            's3',
            aws_access_key_id=current_app.config['AWS_ACCESS_KEY'],
            aws_secret_access_key=current_app.config['AWS_SECRET_KEY']
        )
        patch_name = PATCH_NAME_FORMAT.format(
            revision_id=self.revision_id,
            diff_id=self.diff_id,
            timestamp=int(round(datetime.datetime.utcnow().timestamp()))
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
    """Phabricator has not returned a diff for a given id."""

    def __init__(self, diff_id):
        super().__init__()
        self.diff_id = diff_id
