# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
import logging
from json.decoder import JSONDecodeError

import requests
from enum import Enum

logger = logging.getLogger(__name__)


class Statuses(Enum):
    NEEDS_REVIEW = '0'
    NEEDS_REVISION = '1'
    APPROVED = '2'
    CLOSED = '3'
    ABANDONED = '4'
    CHANGES_PLANNED = '5'


CLOSED_STATUSES = [Statuses.CLOSED, Statuses.ABANDONED]
OPEN_STATUSES = [
    Statuses.NEEDS_REVIEW, Statuses.NEEDS_REVISION, Statuses.APPROVED,
    Statuses.CHANGES_PLANNED
]


class PhabricatorClient:
    """A class to interface with Phabricator's Conduit API.

    All request methods in this class will throw a PhabricatorAPIException if
    Phabricator returns an error response. If there is an actual problem with
    the request to the server or decoding the JSON response, this class will
    bubble up the exception, as a PhabricatorAPIException caused by the
    underlying exception.
    """

    def __init__(self, url, api_token, *, session=None):
        self.api_url = url + 'api/' if url[-1] == '/' else url + '/api/'
        self.api_token = api_token
        self.session = session or self.create_session()

    def call_conduit(self, method, **kwargs):
        """Return the result of an RPC call to a conduit method.

        Args:
            **kwargs: Every method parameter is passed as a keyword argument.

        Returns:
            The 'result' key of the conduit method's response or None if
            the 'result' key doesn't exist.

        Raises:
            PhabricatorAPIException:
                if conduit returns an error response.
            requests.exceptions.RequestException:
                if there is a request exception while communicating
                with the conduit API.
        """
        data = {'api.token': self.api_token}
        data.update(self.flatten_params(kwargs))

        try:
            response = self.session.get(
                self.api_url + method, data=data
            ).json()
        except requests.RequestException as exc:
            raise PhabricatorCommunicationException(
                "An error occurred when communicating with Phabricator"
            ) from exc
        except JSONDecodeError as exc:
            raise PhabricatorCommunicationException(
                "Phabricator response could not be decoded as JSON"
            ) from exc

        PhabricatorAPIException.raise_if_error(response)
        return response.get('result')

    @staticmethod
    def create_session():
        return requests.Session()

    @staticmethod
    def flatten_params(params):
        """Flatten nested objects and lists.

        Phabricator requires query data in a application/x-www-form-urlencoded
        format, so we need to flatten our params dictionary."""
        flat = {}
        remaining = list(params.items())

        # Run a depth-ish first search building the parameter name
        # as we traverse the tree.
        while remaining:
            key, o = remaining.pop()
            if isinstance(o, dict):
                gen = o.items()
            elif isinstance(o, list):
                gen = enumerate(o)
            else:
                flat[key] = o
                continue

            remaining.extend(('{}[{}]'.format(key, k), v) for k, v in gen)

        return flat

    def get_revision(self, id=None, phid=None):
        """Gets a revision as defined by the Phabricator API.

        Args:
            id: The integer id of the revision.
            phid: The phid of the revision.

        Returns:
            A dict of the revision data just as it is returned by Phabricator.
            Returns None, if the revision doesn't exist, or if the api key that
            was used to create the PhabricatorClient doesn't have permission to
            view the revision.

        Raises:
            TypeError if both id and phid are provided.
        """
        if id and phid:
            raise TypeError('Please do not use both id and phid at once')

        ids = [id] if id else []
        phids = [phid] if phid else []
        result = self.get_revisions(ids=ids, phids=phids)

        return result[0] if result else None

    def get_revisions(self, ids=[], phids=[]):
        """Gets a list of revisions in one request.

        This function is purely using the `differential.query` with searching
        by ids and phids.

        Args:
            ids: A list of integer the ids of the revisions.
            phids: A list of the phids of the revisions.

        Returns:
            A list of dicts just as it is returned by Phabricator or an
            empty list if no revision has been found.
        """
        if not ids and not phids:
            return []

        return self.call_conduit('differential.query', ids=ids, phids=phids)

    def get_rawdiff(self, diff_id):
        """Get the raw git diff text by diff id.

        Args:
            diff_id: The integer ID of the diff.

        Returns:
            A string holding a Git Diff.
        """
        result = self.call_conduit('differential.getrawdiff', diffID=diff_id)
        return result if result else None

    def get_diff(self, id=None, phid=None):
        """Get a diff by either integer id or phid.

        Args:
            id: The integer id of the diff.
            phid: The PHID of the diff. This will be used instead if provided.

        Returns
            A hash containing the full information about the diff exactly
            as returned by Phabricator's API.

            Note: Due to the nature of Phabricator's API, the diff request may
            be very large if the diff itself is large. This is because
            Phabricator includes the line by line changes in the JSON payload.
            Be aware of this, as it can lead to large and long requests.
        """
        diff_id = int(id) if id else None
        if phid:
            diff_id = self.diff_phid_to_id(phid)

        if not diff_id:
            return None

        result = self.call_conduit('differential.querydiffs', ids=[diff_id])
        return result[str(diff_id)] if result else None

    def diff_phid_to_id(self, phid):
        """Convert Diff PHID to the Diff id.

        Send a request to Phabricator's `phid.query` API.
        Extract Diff id from URI provided in result.

        Args:
            phid: The PHID of the diff.

        Returns:
            Integer representing the Diff id in Phabricator
        """
        phid_query_result = self.call_conduit('phid.query', phids=[phid])
        if phid_query_result:
            diff_uri = phid_query_result[phid]['uri']
            return self._extract_diff_id_from_uri(diff_uri)
        else:
            return None

    def get_reviewers(self, revision_id):
        """Gets reviewers of the revision.

        Requests `revision.search` to get the reviewers data. Then - with the
        received reviewerPHID keys - a new request is made to `user.search`
        to get the user info. A new dict indexed by phid is created with keys
        and values from both requests.

        Attributes:
            revision_id: integer, ID of the revision in Phabricator

        Returns:
            A list sorted by phid of combined reviewers and users info.
        """
        # Get basic information about the reviewers
        # reviewerPHID, actorPHID, status, and isBlocking is provided
        result = self.call_conduit(
            'differential.revision.search',
            constraints={'ids': [revision_id]},
            attachments={'reviewers': 1}
        )

        has_reviewers = (
            result['data'] and
            result['data'][0]['attachments']['reviewers']['reviewers']
        )
        if not has_reviewers:
            return {}

        reviewers_data = (
            result['data'][0]['attachments']['reviewers']['reviewers']
        )

        # Get user info of all revision reviewers
        reviewers_phids = [r['reviewerPHID'] for r in reviewers_data]
        result = self.call_conduit(
            'user.search', constraints={'phids': reviewers_phids}
        )
        reviewers_info = result['data']

        if len(reviewers_data) != len(reviewers_info):
            logger.warning(
                {
                    'reviewers_phids': reviewers_phids,
                    'users_phids': [r['phid'] for r in reviewers_info],
                    'revision_id': revision_id,
                    'msg': 'Number of reviewers and user accounts do not match'
                }, 'get_reviewers.warning'
            )

        # Create a dict of all reviewers and users info identified by PHID.
        reviewers_dict = {}
        for data in reviewers_data, reviewers_info:
            for reviewer in data:
                phid = reviewer.get('reviewerPHID') or reviewer.get('phid')
                reviewers_dict[phid] = reviewers_dict.get(phid, {})
                reviewers_dict[phid].update(reviewer)

        # Translate the dict to a list sorted by the key (PHID)
        return [
            r[1] for r in sorted(reviewers_dict.items(), key=lambda x: x[0])
        ]

    def get_current_user(self):
        """Gets the information of the user making this request.

        Returns:
            A hash containing the information of the user that owns the api key
            that was used to initialize this PhabricatorClient.
        """
        return self.call_conduit('user.whoami')

    def get_user(self, phid):
        """Gets the information of the user based on their phid.

        Args:
            phid: The phid of the user to lookup.

        Returns:
            A hash containing the user information, or an None if the user
            could not be found.
        """
        result = self.call_conduit('user.query', phids=[phid])
        return result[0] if result else None

    def get_repo(self, phid):
        """Get full information about a repo based on its phid.

        Args:
            phid: The phid of the repo to lookup. If None, None will be
                returned.

        Returns:
            A dict containing the repo info, or None if the repo isn't found.
        """
        if phid:
            result = self.call_conduit(
                'diffusion.repository.search', constraints={'phids': [phid]}
            )
            return result['data'][0] if result['data'] else None
        else:
            return None

    def get_revision_author(self, revision):
        """Return the Phabricator User data for a revision's author.

        Args:
            revision: A dictionary of Phabricator Revision data.

        Returns:
            A dictionary of Phabricator User data.
        """
        return self.get_user(revision['authorPHID'])

    def check_connection(self):
        """Test the Phabricator API connection with conduit.ping.

        Will return success iff the response has a HTTP status code of 200, the
        JSON response is a well-formed Phabricator API response, and if there
        is no connection error (like a hostname lookup error or timeout).

        Raises a PhabricatorAPIException on error.
        """
        try:
            self.call_conduit('conduit.ping')
        except (requests.ConnectionError, requests.Timeout) as exc:
            logging.debug("error calling 'conduit.ping': %s", exc)
            raise PhabricatorAPIException from exc

    def verify_api_key(self):
        """ Verifies that the api key this instance was created with is valid.

        Returns False if Phabricator returns an error code when checking this
        api key. Returns True if no errors are found.
        """
        try:
            self.get_current_user()
        except PhabricatorAPIException:
            return False
        return True

    def get_dependency_tree(self, revision, recursive=True):
        """Generator yielding revisions from the dependency tree.

        Get parent revisions for the provided revision. If recursive is True
        try to get parent's revisions.

        Args:
            revision: Revision which dependency tree will be examined
            recursive: (bool) should parent's dependency tree be returned?

        Returns:
            A generator of the dependency tree revisions
        """
        phids = revision['auxiliary'].get('phabricator:depends-on', [])
        if phids:
            revisions = self.get_revisions(phids=phids)
            for revision in revisions:
                yield revision

                if recursive:
                    yield from self.get_dependency_tree(revision)

    def get_first_open_parent_revision(self, revision):
        """Find first open parent revision.

        Args:
            revision: Revision which dependency tree will be examined

        Returns:
            Open Revision or None
        """

        dependency_tree = self.get_dependency_tree(revision)
        for dependency in dependency_tree:
            if Statuses(dependency['status']) in OPEN_STATUSES:
                return dependency

    @staticmethod
    def extract_bug_id(revision):
        """Helper method to extract the bug id from a Phabricator revision.

        Args:
            revision: dict containing revision info.

        Returns:
            (int) Bugzilla bug id or None
        """
        bug_id = revision['auxiliary'].get('bugzilla.bug-id', None)
        try:
            return int(bug_id)
        except (TypeError, ValueError):
            return None

    def _extract_diff_id_from_uri(self, uri):
        """Extract a diff ID from a Diff uri."""
        # The diff is part of a URI, such as
        # "https://secure.phabricator.com/differential/diff/43480/".
        parts = uri.rsplit('/', 4)

        # Check that the URI Path is something we understand.  Fail if the
        # URI path changed (signalling that the diff id part of the URI may
        # be in a different segment of the URI string).
        if parts[1:-2] != ['differential', 'diff']:
            raise RuntimeError(
                "Phabricator Diff URI parsing error: The "
                "URI {} is not in a format we "
                "understand!".format(uri)
            )

        # Take the second-last member because of the trailing slash on the URL.
        return int(parts[-2])


class PhabricatorAPIException(Exception):
    """Exception to be raised when Phabricator returns an error response."""

    def __init__(self, *args, error_code=None, error_info=None):
        super().__init__(*args)
        self.error_code = error_code
        self.error_info = error_info

    @classmethod
    def raise_if_error(cls, response_body):
        """Raise a PhabricatorAPIException if response_body was an error."""
        if response_body['error_code']:
            raise cls(
                response_body.get('error_info'),
                error_code=response_body.get('error_code'),
                error_info=response_body.get('error_info')
            )


class PhabricatorCommunicationException(PhabricatorAPIException):
    """Exception when communicating with Phabricator fails."""