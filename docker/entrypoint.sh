#!/bin/sh
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# This Source Code Form is "Incompatible With Secondary Licenses", as
# defined by the Mozilla Public License, v. 2.0.

set -ex

case "$1" in
  "upgrade_db")
      TARGET=${2:-heads}
      python landoapi/manage.py upgrade --target $TARGET
      ;;
  "downgrade_db")
      python landoapi/manage.py downgrade $2
      ;;
  *)
      exec "$@"
      ;;
esac
