# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from datetime import datetime
from flask import current_app

from landoapi.models.patch import Patch
from landoapi.phabricator_client import PhabricatorClient
from landoapi.storage import db
from landoapi.transplant_client import TransplantClient
from landoapi.phabricator import revision_id_to_int

logger = logging.getLogger(__name__)

TRANSPLANT_JOB_PENDING = 'pending'
TRANSPLANT_JOB_STARTED = 'started'
TRANSPLANT_JOB_LANDED = 'landed'
TRANSPLANT_JOB_FAILED = 'failed'


class Landing(db.Model):
    """Represents the landing process in Autoland.

    Landing is communicating with Autoland via TransplantClient.
    Landing is communicating with Phabricator via PhabricatorClient.
    Landing object might be saved to database without creation of the actual
    landing in Autoland. It is done before landing request to construct
    required "pingback URL" and save related Patch objects.
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
    status = db.Column(db.String(30))
    error = db.Column(db.String(128), default='')
    result = db.Column(db.String(128), default='')
    created = db.Column(db.DateTime())
    updated = db.Column(db.DateTime())
    patches = db.relationship('Patch', backref='landing')

    def __init__(
        self,
        request_id=None,
        revision_id=None,
        diff_id=None,
        status=TRANSPLANT_JOB_PENDING
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
            * Landing object is created (without request_id)
            * Revision and Diff are loaded from Phabricator.
            * Patch is created and uploaded to S3 bucket.
            * A request to land the patch is send to Transplant client.
            * Created landing object is updated with returned `request_id`,
              it is then saved and returned.

        Args:
            revision_id: The id of the revision to be landed
            diff_id: The id of the diff to be landed
            phabricator_api_key: API Key to identify in Phabricator

        Returns:
            A new Landing object

        Raises:
            LandingNotCreatedException: landing request failed in Transplant
            RevisionNotFoundException: PhabricatorClient returned no
                revision for given revision_id
        """
        phab = PhabricatorClient(phabricator_api_key)

        session = db.create_scoped_session()

        try:
            # Save landing to make sure we've got the callback URL.
            landing = cls(revision_id=revision_id, diff_id=diff_id)
            landing.save(session=session, commit=False)

            revision = phab.get_revision(id=revision_id)
            if not revision:
                raise RevisionNotFoundException(revision_id)

            # Create a patch for the revision.
            patch = Patch(landing.id, revision, diff_id, phabricator=phab)
            patch.upload()
            patch.save(session=session, commit=False)

            repo = phab.get_revision_repo(revision)

            # Define the pingback URL.
            callback = '{host_url}/landings/{id}/update'.format(
                host_url=current_app.config['PINGBACK_HOST_URL'],
                id=landing.id
            )

            trans = TransplantClient()
            # The LDAP username used here has to be the username of the patch
            # pusher (the person who pushed the 'Land it!' button).
            # FIXME: change ldap_username@example.com to the real data
            #        retrieved from Auth0 userinfo
            request_id = trans.land(
                'ldap_username@example.com', [patch.s3_url], repo['uri'],
                callback
            )
            if not request_id:
                raise LandingNotCreatedException

            landing.request_id = int(request_id)
            landing.status = TRANSPLANT_JOB_STARTED
        except:
            session.rollback()
            raise

        session.commit()

        logger.info(
            {
                'revision_id': landing.revision_id,
                'landing_id': landing.id,
                'msg': 'landing created for revision'
            }, 'landing.success'
        )

        return landing

    def save(self, session=None, commit=True):
        """Save object to db."""
        self.updated = datetime.utcnow()
        session = session or db.session
        if not self.id:
            session.add(self)

        if commit:
            return session.commit()

    def __repr__(self):
        return '<Landing: %s>' % self.id

    def serialize(self):
        """Serialize to JSON compatible dictionary."""
        return {
            'id': self.id,
            'revision_id': self.revision_id,
            'request_id': self.request_id,
            'diff_id': self.diff_id,
            'status': self.status,
            'error_msg': self.error,
            'result': self.result or '',
            'created': self.created.isoformat(),
            'updated': self.updated.isoformat()
        }


class LandingNotCreatedException(Exception):
    """Transplant service failed to land a revision."""
    pass


class RevisionNotFoundException(Exception):
    """Phabricator returned 404 for a given revision id."""

    def __init__(self, revision_id):
        super().__init__()
        self.revision_id = revision_id
