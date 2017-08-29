# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import boto3
import logging
import tempfile

from flask import current_app

from landoapi.hgexportbuilder import build_patch_for_revision
from landoapi.phabricator_client import PhabricatorClient

logger = logging.getLogger(__name__)

PATCH_URL_FORMAT = 's3://{bucket}/{patch_name}'


class Patch:
    def __init__(self, revision, diff_id, phabricator_api_key=None):
        """Create a patch.

        Args:
            revision: The revision as defined by Phabricator API
            diff_id: The id of the diff to be landed
            phabricator_api_key: API Key to identify in Phabricator

        Request diff and revision author from Phabricator API.
        Build the patch contents and upload to S3.
        """
        phab = PhabricatorClient(phabricator_api_key)
        diff = phab.get_rawdiff(diff_id)

        if not diff:
            raise DiffNotFoundException(diff_id)

        author = phab.get_revision_author(revision)
        hgpatch = build_patch_for_revision(diff, author, revision)

        # Upload patch to S3.
        self.s3_url = _upload_patch_to_s3(hgpatch, revision['id'], diff_id)

        logger.info(
            {
                'patch_url': self.s3_url,
                'msg': 'Patch file uploaded'
            }, 'landing.patch_uploaded'
        )


class DiffNotFoundException(Exception):
    """ Phabricator returned 404 for a given diff id. """

    def __init__(self, diff_id):
        super().__init__()
        self.diff_id = diff_id


def _upload_patch_to_s3(patch, revision_id, diff_id):
    """Save patch in S3 bucket.

    Creates a temporary file and uploads it to an S3 bucket.

    Args:
        patch: Text to be saved
        revision_id: String ID of the revision (ex. 'D123')
        diff_id: The integer ID of the raw diff

    Returns
        String representing the patch's URL in S3
        (ex. 's3://{bucket_name}/D123_1.patch')
    """
    s3 = boto3.resource(
        's3',
        aws_access_key_id=current_app.config['AWS_ACCESS_KEY'],
        aws_secret_access_key=current_app.config['AWS_SECRET_KEY']
    )
    patch_name = 'D{revision_id}_{diff_id}.patch'.format(
        revision_id=revision_id, diff_id=diff_id
    )
    bucket = current_app.config['PATCH_BUCKET_NAME']
    patch_url = PATCH_URL_FORMAT.format(bucket=bucket, patch_name=patch_name)
    with tempfile.TemporaryFile() as patchfile:
        patchfile.write(patch.encode('utf-8'))
        patchfile.seek(0)
        s3.meta.client.upload_fileobj(patchfile, bucket, patch_name)

    return patch_url
