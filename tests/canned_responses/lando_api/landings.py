# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# yapf: disable
CANNED_LANDING_LIST_1 = [
    {
        'id': 1,
        'request_id': 1,
        'revision_id': 'D1',
        'diff_id': 1,
        'active_diff_id': None,
        'status': 'started',
        'error_msg': '',
        'result': '',
        'patch_urls': []
    }, {
        'id': 2,
        'request_id': 2,
        'revision_id': 'D1',
        'diff_id': 2,
        'active_diff_id': None,
        'status': 'finished',
        'error_msg': '',
        'result': '',
        'patch_urls': []
    }, {
        'id': 4,
        'request_id': 4,
        'revision_id': 'D1',
        'diff_id': 4,
        'active_diff_id': None,
        'status': 'started',
        'error_msg': '',
        'result': '',
        'patch_urls': []
    }
]

CANNED_LANDING_1 = {
    'id': 1,
    'status': 'started',
    'request_id': 1,
    'revision_id': 'D1',
    'diff_id': 1,
    'active_diff_id': None,
    'error_msg': '',
    'result': '',
    'patch_urls': []
}

CANNED_LANDING_FACTORY_1 = {
    'id': 1,
    'status': 'started',
    'request_id': 3,
    'revision_id': 'D1',
    'active_diff_id': None,
    'diff_id': 2,
    'error_msg': '',
    'result': '',
    'patch_urls': ['s3://landoapi.test.bucket/L1_D1_2.patch']
}

CANNED_LANDING_FACTORY_2 = {
    'id': 2,
    'status': 'started',
    'request_id': 2,
    'revision_id': 'D1',
    'diff_id': 1,
    'active_diff_id': None,
    'error_msg': '',
    'result': '',
    'patch_urls': []
}
