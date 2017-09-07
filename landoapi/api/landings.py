# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Transplant API
See the OpenAPI Specification for this API in the spec/swagger.yml file.
"""
import hmac
import json
import logging
import os

from connexion import problem
from flask import request
from sqlalchemy.orm.exc import NoResultFound
from landoapi.models.landing import (
    InactiveDiffException, Landing, LandingNotCreatedException,
    MultipleParentRevisionsDetected, RevisionNotFoundException,
    TRANSPLANT_JOB_FAILED, TRANSPLANT_JOB_LANDED
)
from landoapi.models.patch import DiffNotFoundException

logger = logging.getLogger(__name__)
TRANSPLANT_API_KEY = os.getenv('TRANSPLANT_API_KEY')


def land(data, api_key=None):
    """ API endpoint at /revisions/{id}/transplants to land revision. """
    # get revision_id from body
    revision_id = data['revision_id']
    diff_id = data['diff_id']
    force = data.get('force_inactive_diff', False)
    logger.info(
        {
            'path': request.path,
            'method': request.method,
            'data': data,
            'msg': 'landing requested by user'
        }, 'landing.invoke'
    )
    try:
        landing = Landing.create(revision_id, diff_id, api_key, force)
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
    except MultipleParentRevisionsDetected as exc:
        # Dependency structure does not allow to automatically land
        # the revision
        logger.warning(
            {
                'revision': revision_id,
                'error_revision_id': exc.revision_id,
                'msg': 'Multiple revision dependency detected',
            }, 'landing.failure'
        )
        return problem(
            400,
            'Multiple parent revisions detected',
            'Revision {revision_id} has multiple parents. '
            'Please proceed with manual landing process.'.format(
                revision_id=exc.revision_id
            ),
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400'
        )
    except InactiveDiffException as exc:
        # Attempt to land an inactive diff
        logger.info(
            {
                'revision': revision_id,
                'diff_id': exc.diff_id,
                'active_diff_id': exc.active_diff_id
            }, 'landing.failure'
        )
        return problem(
            409,
            'Inactive Diff',
            'The requested diff is not the active one for the revision.',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/409'
        )
    except LandingNotCreatedException as exc:
        # We could not find a matching revision.
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

    return {'id': landing.id}, 202


def get_list(revision_id=None, status=None):
    """ API endpoint at /landings to return all Landing objects related to a
    Revision or of specific status.
    """
    kwargs = {}
    if revision_id:
        kwargs['revision_id'] = revision_id

    if status:
        kwargs['status'] = status

    landings = Landing.query.filter_by(**kwargs).all()
    return list(map(lambda l: l.serialize(), landings)), 200


def get(landing_id):
    """ API endpoint at /landings/{landing_id} to return stored Landing.
    """
    landing = Landing.query.get(landing_id)
    if not landing:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    return landing.serialize(), 200


def _not_authorized_problem():
    return problem(
        403,
        'Not Authorized',
        'You\'re not authorized to proceed.',
        type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403'
    )


def update(landing_id, data):
    """Update landing on pingback from Transplant.

    data contains following fields:
    request_id: integer
        id of the landing request in Transplant
    tree: string
        tree name as per treestatus
    rev: string
        matching phabricator revision identifier
    destination: string
        full url of destination repo
    trysyntax: string
        change will be pushed to try or empty string
    landed: boolean;
        true when operation was successful
    error_msg: string
        error message if landed == false
        empty string if landed == true
    result: string
        revision (sha) of push if landed == true
        empty string if landed == false

    API-Key header is required to authenticate Transplant API
    """
    if os.getenv('PINGBACK_ENABLED', 'n') != 'y':
        logger.warning(
            {
                'request_id': data.get('request_id', None),
                'landing_id': landing_id,
                'remote_addr': request.remote_addr,
                'msg': 'Attempt to access a disabled pingback',
            }, 'pingback.warning'
        )
        return _not_authorized_problem()

    if not hmac.compare_digest(
        request.headers.get('API-Key', ''), TRANSPLANT_API_KEY
    ):
        logger.warning(
            {
                'request_id': data.get('request_id', None),
                'landing_id': landing_id,
                'remote_addr': request.remote_addr,
                'msg': 'Wrong API Key',
            }, 'pingback.error'
        )
        return _not_authorized_problem()

    try:
        landing = Landing.query.filter_by(
            id=landing_id, request_id=data['request_id']
        ).one()
    except NoResultFound:
        return problem(
            404,
            'Landing not found',
            'The requested Landing does not exist',
            type='https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404'
        )

    landing.error = data.get('error_msg', '')
    landing.result = data.get('result', '')
    landing.status = TRANSPLANT_JOB_LANDED if data['landed'
                                                  ] else TRANSPLANT_JOB_FAILED
    landing.save()
    return {}, 202
