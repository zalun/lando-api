# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


def revision_id_to_int(revision_id):
    """Convert revision id to int.

    Revision id might come as a string with a `'D'` in front of the number.
    123, '123', 'D123' will be returned as 123.

    Args:
        revision_id: integer or string representing a revision id.
            In example 123, '123', 'D123'

    Returns:
        Integer representing the revision id in Phabricator
    """
    if isinstance(revision_id, str):
        return int(revision_id.strip().replace('D', ''))
    return revision_id
