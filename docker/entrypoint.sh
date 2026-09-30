#!/bin/sh
# Container entrypoint.
#
# nexsift must not run as root. A data directory mounted from outside carries the rights of the host, and
# those rarely match the user inside the image by chance. So the container briefly fixes the rights as root
# and then drops to the user "nexsift". PUID and PGID say which host user owns the files.

set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Started without root already ("user:" in the compose file): nothing to fix.
if [ "$(id -u)" != "0" ]; then
    exec "$@"
fi

if [ "$(id -g nexsift)" != "$PGID" ]; then
    groupmod -o -g "$PGID" nexsift
fi
if [ "$(id -u nexsift)" != "$PUID" ]; then
    usermod -o -u "$PUID" nexsift
fi

mkdir -p /data

# Only touch it when the owner is wrong. A "chown -R" on every start costs time on large directories.
if [ "$(stat -c %u /data)" != "$PUID" ] || [ "$(stat -c %g /data)" != "$PGID" ]; then
    echo "nexsift: adjusting ownership of the data directory to $PUID:$PGID."
    chown -R "$PUID:$PGID" /data
fi

# Owner does not mean writable: on a NAS the directory can belong to the right user and still be closed by
# an access list. Then a long Python error would appear mid-start that nobody reads the cause from. So we
# really write here, as the user that does it later.
if ! gosu nexsift sh -c 'touch /data/.write-test' 2>/dev/null; then
    echo "nexsift: the data directory is not writable." >&2
    echo "" >&2
    echo "  nexsift runs as uid $PUID, gid $PGID and cannot write to the" >&2
    echo "  directory mounted at /data. Nothing has been started." >&2
    echo "" >&2
    echo "  On the host, that directory needs to belong to that user:" >&2
    echo "" >&2
    echo "      sudo chown -R $PUID:$PGID /path/to/your/data" >&2
    echo "      sudo chmod -R u+rwX /path/to/your/data" >&2
    echo "" >&2
    echo "  PUID and PGID are set in your compose file. To find your own," >&2
    echo "  run 'id' on the host and use the uid and gid it reports." >&2
    exit 1
fi
rm -f /data/.write-test

exec gosu nexsift "$@"
