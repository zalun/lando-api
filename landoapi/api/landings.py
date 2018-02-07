# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Landing API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import hashlib
import hmac
import json
import logging

from connexion import problem
from flask import current_app, g, jsonify, request
from sqlalchemy.orm.exc import NoResultFound

from landoapi import auth
from landoapi.decorators import require_phabricator_api_key
from landoapi.models.landing import (
    InactiveDiffException,
    Landing,
    LandingNotCreatedException,
    OpenParentException,
    OverrideDiffException,
    RevisionAlreadyLandedException,
    RevisionNotFoundException,
)
from landoapi.models.patch import (
    DiffNotFoundException, DiffNotInRevisionException
)
from landoapi.validation import revision_id_to_int

logger = logging.getLogger(__name__)


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def post(data):
    """API endpoint at POST /landings to land revision."""
    if not g.auth0_user.email:
        return problem(
            403,
            'Not Authorized',
            'You do not have a Mozilla verified email address.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403'
        )

    if not g.auth0_user.can_land_changes():
        return problem(
            403,
            'Not Authorized',
            'You do not have the required permissions to request landing.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403'
        )

    # get revision_id from body
    revision_id = revision_id_to_int(data['revision_id'])
    diff_id = data['diff_id']
    override_diff_id = data.get('force_override_of_diff_id')
    logger.info(
        {
            'path': request.path,
            'method': request.method,
            'data': data,
            'msg': 'landing requested by user'
        }, 'landing.invoke'
    )
    try:
        landing = Landing.create(
            revision_id,
            diff_id,
            g.auth0_user.email,
            g.phabricator,
            override_diff_id=override_diff_id
        )
    except RevisionAlreadyLandedException as exc:
        logger.warning(
            {
                'revision': exc.revision,
                'msg': 'Attempt to land an already landed revision'
            }, 'landing.warning'
        )
        msg_title = 'Revision is already {}'.format(exc.revision.status.value)
        if diff_id == exc.revision.diff_id:
            msg = '{} using the same Diff'.format(msg_title)
        else:
            msg = '{} using Diff {}'.format(msg_title, exc.revision.diff_id)
        return problem(
            409,
            msg_title,
            msg,
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )
    except RevisionNotFoundException:
        # We could not find a matching revision.
        logger.info(
            {
                'revision': revision_id,
                'msg': 'revision not found'
            }, 'landing.failure'
        )
        return problem(
            404,
            'Revision not found',
            'The requested revision does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )
    except DiffNotFoundException:
        # We could not find a matching diff
        logger.info(
            {
                'diff': diff_id,
                'msg': 'diff not found'
            }, 'landing.failure'
        )
        return problem(
            404,
            'Diff not found',
            'The requested diff does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )
    except InactiveDiffException as exc:
        # Attempt to land an inactive diff
        logger.info(
            {
                'revision': revision_id,
                'diff_id': exc.diff_id,
                'active_diff_id': exc.active_diff_id,
                'msg': 'Requested to land an inactive diff'
            }, 'landing.failure'
        )
        return problem(
            409,
            'Inactive Diff',
            'The requested diff is not the active one for this revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409'
        )
    except OpenParentException as exc:
        # One of the parent revisions is still open
        logger.error(
            {
                'revision_id': revision_id,
                'open_revision_id': exc.open_revision_id,
                'msg': 'Attempt to land a revision with an open parent'
            }, 'landing.error'
        )
        return problem(
            409,
            'Parent revision is open',
            'At least one of the parent revisions (D{}) is open.'
            .format(exc.open_revision_id),
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409'
        )
    except OverrideDiffException as exc:
        # Wrong diff chosen to override.
        logger.info(
            {
                'revision': revision_id,
                'diff_id': exc.diff_id,
                'active_diff_id': exc.active_diff_id,
                'override_diff_id': exc.override_diff_id,
                'msg': 'Requested override_diff_id is not the active one'
            }, 'landing.failure'
        )
        return problem(
            409,
            'Overriding inactive diff',
            'The diff to override is not the active one for this revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409'
        )
    except LandingNotCreatedException as exc:
        logger.info(
            {
                'revision': revision_id,
                'exc': exc,
                'msg': 'error creating landing',
            }, 'landing.error'
        )
        return problem(
            502,
            'Landing not created',
            'The requested revision does exist, but landing failed.'
            'Please retry your request at a later time.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502'
        )
    except DiffNotInRevisionException:
        # Diff's revisionID field does not equal revision_id
        logger.info(
            {
                'revision': revision_id,
                'diff_id': diff_id,
                'msg': 'Diff not it revision.',
            }, 'landing.error'
        )
        return problem(
            400,
            'Diff not related to the revision',
            'The requested diff is not related to the requested revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )

    return {'id': landing.id}, 202


@require_phabricator_api_key(optional=True)
def get_list(revision_id):
    """API endpoint at GET /landings to return a list of Landing objects."""
    # Verify that the client is permitted to see the associated revision.
    revision_id = revision_id_to_int(revision_id)
    revision = g.phabricator.get_revision(id=revision_id)
    if not revision:
        return problem(
            404,
            'Revision not found',
            'The revision does not exist or you lack permission to see it.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    landings = Landing.query.filter_by(revision_id=revision_id).all()
    return [l.serialize() for l in landings], 200


@require_phabricator_api_key(optional=True)
def get(landing_id):
    """API endpoint at /landings/{landing_id} to return stored Landing."""
    landing = Landing.query.get(landing_id)

    if landing:
        # Verify that the client has permission to see the associated revision.
        revision = g.phabricator.get_revision(id=landing.revision_id)
        if revision:
            return landing.serialize(), 200

    return problem(
        404,
        'Landing not found',
        'The landing does not exist or you lack permission to see it.',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
    )


def update(data):
    """Update landing on pingback from Transplant.

    API-Key header is required to authenticate Transplant API

    data contains following fields:
        request_id: integer (required)
            id of the landing request in Transplant
        landed: boolean (required)
            true when operation was successful
        tree: string
            tree name as per treestatus
        rev: string
            matching phabricator revision identifier
        destination: string
            full url of destination repo
        trysyntax: string
            change will be pushed to try or empty string
        error_msg: string
            error message if landed == false
            empty string if landed == true
        result: string
            revision (sha) of push if landed == true
            empty string if landed == false
    """
    if current_app.config['PINGBACK_ENABLED'] != 'y':
        logger.warning(
            {
                'data': data,
                'remote_addr': request.remote_addr,
                'msg': 'Attempt to access a disabled pingback',
            }, 'pingback.warning'
        )
        return _not_authorized_problem()

    passed_key = request.headers.get('API-Key', '')
    required_key = current_app.config['TRANSPLANT_API_KEY']
    if not hmac.compare_digest(passed_key, required_key):
        logger.warning(
            {
                'data': data,
                'remote_addr': request.remote_addr,
                'msg': 'Wrong API Key',
            }, 'pingback.error'
        )
        return _not_authorized_problem()

    try:
        landing = Landing.query.filter_by(request_id=data['request_id']).one()
    except NoResultFound:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    landing.update_from_transplant(
        data['landed'],
        error=data.get('error_msg', ''),
        result=data.get('result', '')
    )
    landing.save()
    return {}, 200


@auth.require_auth0(scopes=('lando', 'profile', 'email'), userinfo=True)
@require_phabricator_api_key(optional=True)
def dryrun(data):
    """API endpoint at /landings/dryrun.

    Returns a LandingAssessment for the given Revision ID.
    """
    assessment = LandingAssessment([], [])

    id = revision_id_to_int(data['revision_id'])
    revision = g.phabricator.get_revision(id)

    assessment.run_checks(revision)

    return jsonify(assessment.to_dict())


class LandingAssessment:
    """Represents an assessment of issues that may block a revision landing.

    Attributes:
        warnings: List of warning dictionaries. Each dict must have an 'id'
            key holding the warning ID. e.g. {'id': 'W201', ...}
        problems: List of problem dictionaries Each dict must have an 'id'
            key holding the problem ID. e.g. {'id': 'E406', ...}
    """

    def __init__(self, warnings, problems):
        self.warnings = warnings
        self.problems = problems

    def to_dict(self):
        """Return the assessment as a dict.

        Includes the appropriate confirmation_token for any warnings present.
        """
        return {
            'confirmation_token': self.hash_warning_list(),
            'warnings': self.warnings,
            'problems': self.problems,
        }

    def hash_warning_list(self):
        """Return a hash of our warning dictionaries.

        Hashes are generated in a cross-machine comparable way.

        This function takes a list of warning dictionaries.  Each dictionary
        must have an 'id' key that holds the unique warning ID.

        E.g.:
        [
            {'id': 'W201', ...},
            {'id': 'W500', ...},
            ...
        ]

        This function generates a hash of warnings dictionaries that can be
        passed to a client across the network, then returned by that client
        and compared to the warnings in a new landing process.  That landing
        process could be happening on a completely different machine than the
        one that generated the original hash.  This function goes to pains to
        ensure that a hash of the same set of warning list dictionaries on
        separate machines will match.

        Args:
            warning_list: A list of warning dictionaries.  The 'id' key and
                value must be JSON-serializable.

        Returns: String.  Returns None if given an empty list.
        """
        if not self.warnings:
            return None

        # The warning ID and message should be stable across machines.

        # First de-duplicate the list of dicts using the ID field.  If there
        # is more than one warning with the same ID and different fields then
        # the last entry in the warning list wins.
        warnings_dict = dict((w['id'], w) for w in self.warnings)

        # Assume we are trying to encode a JSON-serializable warning_list
        # structure - keys and values are only simple types, not objects.  A
        # TypeError will be thrown if the caller accidentally tries to
        # serialize something funky. Also sort the warning dict items and
        # nested dict items so the same hash can be generated on different
        # machines. See https://stackoverflow.com/a/10288255 and
        # https://stackoverflow.com/questions/5884066/hashing-a-dictionary
        # for a discussion of why this is tricky!
        warnings_json = json.dumps(
            warnings_dict, sort_keys=True
        ).encode('UTF-8')
        return hashlib.sha256(warnings_json).hexdigest()

    def run_checks(self, revision):
        self.check_open_parent(revision)

    def check_open_parent(self, revision):
        open_revision = g.phabricator.get_first_open_parent_revision(revision)
        if open_revision:
            message = 'One of the parent revisions (D{}) is open.'.format(
                open_revision['id']
            )
            self.problems.append(
                {
                    'id': 'E1',
                    'open_revision_id': open_revision['id'],
                    'message': message
                }
            )


def _not_authorized_problem():
    return problem(
        403,
        'Not Authorized',
        'You\'re not authorized to proceed.',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403'
    )
