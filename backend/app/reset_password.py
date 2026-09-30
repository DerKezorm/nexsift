"""The way back in when the password is forgotten and no sign-in provider works:

    docker exec -it nexsift python -m app.reset_password

Asks for a new password twice. Whoever can run commands in the container owns the data anyway.
"""

from __future__ import annotations

import getpass
import sys

from .db import SessionLocal, init_db
from .security import MIN_PASSWORD
from .services import accounts, settings_service


def main() -> int:
    init_db()
    first = getpass.getpass("New password: ")
    if len(first) < MIN_PASSWORD:
        print(f"Use at least {MIN_PASSWORD} characters.")
        return 1
    if getpass.getpass("Once more: ") != first:
        print("The two do not match.")
        return 1
    with SessionLocal() as db:
        try:
            account = accounts.reset_password(db, first)
        except accounts.AccountError as error:
            print(error.message)
            return 1
        # A forgotten password with the password sign-in switched off would lock the door again at once.
        settings_service.save(db, {"password_login": True})
    print(f"Done. Sign in as {account.name} with the new password.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
