# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""Landing model representing a Transplant landing request."""
import enum
import logging
from datetime import datetime

from flask import current_app

from landoapi.models.patch import Patch
from landoapi.phabricator_client import PhabricatorClient
from landoapi.storage import db
from landoapi.transplant_client import TransplantClient, TransplantAPIException

logger = logging.getLogger(__name__)


@enum.unique
class STATUS(enum.Enum):
    """Status of the landing request."""
    # Landing instantiated. Preparing for landing.
    LANDING_CREATED = 'created'

    # Set from pingback
    TRANSPLANT_JOB_STARTED = 'started'
    TRANSPLANT_JOB_LANDED = 'landed'
    TRANSPLANT_JOB_FAILED = 'failed'


class Landing(db.Model):
    """Represents the landing process in Autoland.

    Landing is communicating with Autoland via TransplantClient.
    Landing is communicating with Phabricator via PhabricatorClient.
    Landing object might be saved to database before requesting landing
    in Transplant API to construct the required "pingback URL". If landing
    request was aborted orphaned object is removed from database.
    To update the Landing status Transplant is calling provided pingback URL.

    Attributes:
        id: Primary Key
        request_id: Id of the request in Autoland
        revision_id: Phabricator id of the revision to be landed
        diff_id: Phabricator id of the diff to be landed
        status: Status of the landing. Modified by `update` API
        error: Text describing the error if not landed
        result: Revision (sha) of push
        created: DateTime of creation of the Landing object
        updated: DateTime of the last save
        patches: a list of Patch models to land
    """
    __tablename__ = "landings"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, unique=True)
    revision_id = db.Column(db.Integer)
    diff_id = db.Column(db.Integer)
    status = db.Column(db.Enum(STATUS), nullable=False)
    error = db.Column(db.String(128), default='')
    result = db.Column(db.String(128), default='')
    created = db.Column(db.DateTime(), nullable=False)
    updated = db.Column(db.DateTime(), nullable=False)
    patches = db.relationship('Patch', backref='landing')

    def __init__(
        self,
        request_id=None,
        revision_id=None,
        diff_id=None,
        status=STATUS.LANDING_CREATED
    ):
        self.request_id = request_id
        self.revision_id = revision_id
        self.diff_id = diff_id
        self.status = status
        self.created = datetime.utcnow()

    @classmethod
    def create(cls, revision_id, diff_id, phabricator_api_key=None):
        """Land revision.

        A typical successful story:
            * Revision and repo are requested from Phabricator API
            * Patch object loads Diff from Phabricator API and uploads it to S3
            * Landing object is created (without request_id)
            * A request to land the patch is sent to Transplant client.
            * Landing object is updated with returned `request_id`,
              it is then saved.
            * Patch object is updated with relation to Landing and saved.

        Args:
            revision_id: The id of the revision to be landed
            diff_id: The id of the diff to be landed
            phabricator_api_key: API Key to identify in Phabricator

        Returns:
            A new Landing object

        Raises:
            RevisionNotFoundException: PhabricatorClient returned no
                revision for the requested revision_id
        """
        phab = PhabricatorClient(phabricator_api_key)

        revision = phab.get_revision(id=revision_id)
        if not revision:
            raise RevisionNotFoundException(revision_id)

        repo = phab.get_revision_repo(revision)

        # Create a patch instance
        patch = Patch(revision, diff_id, phabricator=phab)
        # Upload patch to S3
        patch.upload()
        patch.save()

        # Save Landing instance to get the callback URL
        landing = cls(revision_id=revision_id, diff_id=diff_id)
        landing.save()
        callback = landing.get_callback_url()

        trans = TransplantClient()
        # The LDAP username used here has to be the username of the patch
        # pusher (the person who pushed the 'Land it!' button).
        # FIXME: change ldap_username@example.com to the real data
        #        retrieved from Auth0 userinfo
        try:
            request_id = trans.land(
                'ldap_username@example.com', [patch.s3_url], repo['uri'],
                callback
            )
        except TransplantAPIException:
            # Landing request failed - delete Landing object
            landing.delete()
            raise

        landing.request_id = request_id
        landing.status = STATUS.TRANSPLANT_JOB_STARTED
        landing.save()
        patch.landing = landing
        patch.save()

        logger.info(
            {
                'revision_id': revision_id,
                'landing_id': landing.id,
                'msg': 'landing created for revision'
            }, 'landing.success'
        )

        return landing

    def set_status(self, **kwargs):
        """Set the status from pingback request."""
        self.error = kwargs.get('error_msg', '')
        self.result = kwargs.get('result', '')
        self.status = STATUS.TRANSPLANT_JOB_LANDED if kwargs[
            'landed'
        ] else STATUS.TRANSPLANT_JOB_FAILED
        self.save()

    def save(self):
        """Save object to db."""
        self.updated = datetime.utcnow()
        if not self.id:
            db.session.add(self)

        return db.session.commit()

    def delete(self):
        """Remove object from db."""
        db.session.delete(self)
        return db.session.commit()

    def get_callback_url(self):
        """Construct the pingback URL."""
        return '{host_url}/landings/{id}/update'.format(
            host_url=current_app.config['PINGBACK_HOST_URL'], id=self.id
        )

    def __repr__(self):
        return '<Landing: %s>' % self.id

    def serialize(self):
        """Serialize to JSON compatible dictionary."""
        return {
            'id': self.id,
            'revision_id': self.revision_id,
            'request_id': self.request_id,
            'diff_id': self.diff_id,
            'status': self.status.value,
            'error_msg': self.error,
            'result': self.result or '',
            'created': self.created.isoformat(),
            'updated': self.updated.isoformat()
        }


class RevisionNotFoundException(Exception):
    """Phabricator returned 404 for the requested revision id."""

    def __init__(self, revision_id):
        super().__init__()
        self.revision_id = revision_id
