# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging

from flask import current_app

from landoapi.models.patch import Patch
from landoapi.phabricator_client import PhabricatorClient
from landoapi.storage import db
from landoapi.transplant_client import TransplantClient

logger = logging.getLogger(__name__)

TRANSPLANT_JOB_PENDING = 'pending'
TRANSPLANT_JOB_STARTED = 'started'
TRANSPLANT_JOB_LANDED = 'landed'
TRANSPLANT_JOB_FAILED = 'failed'


class Landing(db.Model):
    """Represents the landing process in Autoland.

    Columns:
        id: Primary Key
        request_id: Id of the request in Autoland
        revision_id: Phabricator id of the revision to be landed
        diff_id: Phabricator id of the diff to be landed
        active_diff_id: Phabricator id of the diff active at the moment of
            landing
        status: Status of the landing. Modified by `update` API
        error: Text describing the error if not landed
        result: Revision (sha) of push
    Relation:
        patches: a list of Patch models to land

    Landing is communicating with Autoland via TransplantClient.
    Landing is communicating with Phabricator via PhabricatorClient.
    Landing object might be saved to database without creation of the actual
    landing in Autoland. It is done before landing request to construct
    required "pingback URL" and save related Patch objects.
    To update the Landing status Transplant is calling provided pingback URL.
    Active Diff Id is stored only if Lando API was forced to land a specific
    diff.
    """
    __tablename__ = "landings"

    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, unique=True)
    revision_id = db.Column(db.Integer)
    diff_id = db.Column(db.Integer)
    active_diff_id = db.Column(db.Integer)
    status = db.Column(db.Integer)
    error = db.Column(db.String(128), default='')
    result = db.Column(db.String(128), default='')
    patches = db.relationship('Patch', backref='landing')

    def __init__(
        self,
        request_id=None,
        revision_id=None,
        diff_id=None,
        active_diff_id=None,
        status=TRANSPLANT_JOB_PENDING
    ):
        self.request_id = request_id
        self.revision_id = revision_id
        self.diff_id = diff_id
        self.active_diff_id = active_diff_id
        self.status = status

    @classmethod
    def create(
        cls, revision_id, diff_id, phabricator_api_key=None, force=False
    ):
        """ Land revision.

        Args:
            revision_id: The id of the revision to be landed
            diff_id: The id of the diff to be landed
            phabricator_api_key: API Key to identify in Phabricator

        Returns
            A new Landing object

        A typical successful story:
            * Revision and Diff are loaded from Phabricator.
            * Patch is created and uploaded to S3 bucket.
            * Landing object is created (without request_id)
            * A request to land the patch is send to Transplant client.
            * Created landing object is updated with returned `request_id`,
              it is then saved and returned.
        """
        phab = PhabricatorClient(phabricator_api_key)
        revision = phab.get_revision(id=revision_id)

        if not revision:
            raise RevisionNotFoundException(revision_id)

        active_id = phab.get_diff(phid=revision['activeDiffPHID'])['id']

        # Save landing to make sure we've got the callback URL.
        landing = cls(
            revision_id=revision_id,
            diff_id=diff_id,
            active_diff_id=active_id if active_id != diff_id else None
        ).save()

        cls.create_patch(
            landing.id, revision, landing.diff_id, phabricator_api_key
        )

        # If diff used to land revision is not the active one Lando API will
        # failwith a 409 error (used for that case only). Lando UI will then
        # display a modal window where user may confirm to land it anyway.
        # In such case Lando UI will request a new landing with a
        # force_inactive_diff parameter. API will proceed with the landing.
        if not force:
            if diff_id != int(active_id):
                raise InactiveDiffException(diff_id, active_id)
        else:
            logger.warning(
                {
                    'revision_id': landing.revision_id,
                    'diff_id': landing.diff_id,
                    'active_diff_id': active_id,
                    'msg': 'Forced to land an inactive Diff'
                }, 'landing.warning'
            )

        repo = phab.get_revision_repo(revision)

        # Define the pingback URL with the port.
        callback = '{host_url}/landings/{id}/update'.format(
            host_url=current_app.config['PINGBACK_HOST_URL'], id=landing.id
        )

        trans = TransplantClient()
        # The LDAP username used here has to be the username of the patch
        # pusher (the person who pushed the 'Land it!' button).
        # FIXME: change ldap_username@example.com to the real data retrieved
        #        from Auth0 userinfo
        request_id = trans.land(
            'ldap_username@example.com',
            landing.get_patch_urls(), repo['uri'], callback
        )
        if not request_id:
            raise LandingNotCreatedException

        landing.request_id = request_id
        landing.status = TRANSPLANT_JOB_STARTED
        landing.save()

        logger.info(
            {
                'revision_id': landing.revision_id,
                'landing_id': landing.id,
                'msg': 'landing created for revision'
            }, 'landing.success'
        )

        return landing

    @classmethod
    def create_patch(cls, landing_id, revision, diff_id, phabricator_api_key):
        """Creates a Patch for given revision and diff.

        Args:
            landing_id: Id of the Landing object
            revision: Revision as retrieved from Phabricator
            diff_id: The id of the diff to be saved
            phabricator_api_key: API Key to identify in Phabricator

        If revision depends on another revision it is retrieved from the
        Phabricator recursively.
        """
        parent_revisions = revision['auxiliary'].get(
            'phabricator:depends-on', []
        )
        if len(parent_revisions) > 1:
            # TODO Remove debris from db
            raise MultipleParentRevisionsDetected(revision['id'])

        phab = PhabricatorClient(phabricator_api_key)
        parent_id = None

        for r_phid in parent_revisions:
            r = phab.get_revision(phid=r_phid)
            # create parent patch
            parent_id = phab.diff_phid_to_id(r['activeDiffPHID'])
            cls.create_patch(landing_id, r, parent_id, phabricator_api_key)

        Patch(landing_id, revision, diff_id,
              parent_id).upload(phabricator_api_key).save()

    def get_patch_urls(self):
        """ Get list of S3 URLs for all the patches. """
        return [p.s3_url for p in self.patches]

    def save(self):
        """ Save objects in storage. """
        if not self.id:
            db.session.add(self)

        db.session.commit()
        return self

    def __repr__(self):
        return '<Landing: %s>' % self.id

    def serialize(self):
        """ Serialize to JSON compatible dictionary. """
        return {
            'id': self.id,
            'revision_id': self.revision_id,
            'request_id': self.request_id,
            'diff_id': self.diff_id,
            'active_diff_id': self.active_diff_id,
            'status': self.status,
            'error_msg': self.error,
            'result': self.result or '',
            'patch_urls': self.get_patch_urls()
        }


class MultipleParentRevisionsDetected(Exception):
    """ Transplant service failed to land a revision. """

    def __init__(self, revision_id):
        super().__init__()
        self.revision_id = revision_id


class LandingNotCreatedException(Exception):
    """ Transplant service failed to land a revision. """
    pass


class RevisionNotFoundException(Exception):
    """ Phabricator returned 404 for a given revision id. """

    def __init__(self, revision_id):
        super().__init__()
        self.revision_id = revision_id


class InactiveDiffException(Exception):
    """ Diff chosen to land is not the active one """

    def __init__(self, diff_id, active_diff_id):
        super().__init__()
        self.diff_id = diff_id
        self.active_diff_id = active_diff_id
