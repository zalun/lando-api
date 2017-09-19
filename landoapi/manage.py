# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from landoapi.app import create_app
from landoapi.storage import alembic

from flask_script import Manager

app = create_app('/version.json')

manager = Manager(app.app)


@manager.command
def revision(message):
    """Generate a new migration revision."""
    return alembic.revision(message)


@manager.command
def upgrade(target='heads'):
    """Run migration upgrades."""
    return alembic.upgrade(target=target)


@manager.command
def downgrade(target):
    """Run migration upgrades."""
    return alembic.downgrade(target=target)


if __name__ == "__main__":
    manager.run()
