import os
from enum import Enum, auto
from mastodon import Mastodon  # type: ignore
from mastodon.errors import MastodonNetworkError, MastodonIllegalArgumentError  # type: ignore
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, cast


class Timeline(Enum):
    HOME = auto()


class Visibility(Enum):
    PUBLIC = auto()
    UNLISTED = auto()
    PRIVATE = auto()
    DIRECT = auto()


class BadLoginError(Exception):
    pass


class InvalidClientError(Exception):
    pass


class Client:
    SECRETS_LOC: str = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "secrets")
    )
    CLIENT_NAME: str = "Mastodon for VT-100"

    def __init__(self, server: str) -> None:
        if not server.startswith("https://") and "//" not in server:
            # Assume they meant to add this.
            server = "https://" + server

        self.server = server

        # Make sure we have somewhere to store secrets.
        os.makedirs(self.SECRETS_LOC, exist_ok=True)

        # Figure out the secret file name for the server we were asked to connect to.
        creds = self.__get_client_creds_file(server)
        creds_file = os.path.join(self.SECRETS_LOC, creds)

        # If the file doesn't exist, we need to register with the server, this should be
        # a one-time thing.
        try:
            if not os.path.isfile(creds_file):
                Mastodon.create_app(
                    self.CLIENT_NAME, api_base_url=server, to_file=creds_file
                )

            # Now, save the client itself.
            self.__client = Mastodon(client_id=creds_file)
            self.valid = True
        except MastodonNetworkError:
            self.__client = None
            self.valid = False

    def __get_client_creds_file(self, server: str) -> str:
        url = urlparse(server)
        return f"{url.hostname}.clientcred.secret"

    def __assert_valid(self) -> None:
        if not self.valid:
            raise InvalidClientError(f"Invalid client for {self.server}")

    def login(self, username: str, password: str) -> None:
        self.__assert_valid()

        try:
            self.__client.log_in(username, password)
        except MastodonIllegalArgumentError:
            raise BadLoginError("Bad username or password!")

    def fetchTimeline(
        self,
        which: Timeline,
        *,
        limit: int = 20,
        since: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        self.__assert_valid()

        if which == Timeline.HOME:
            statuses = self.__client.timeline(
                timeline="home", limit=limit, max_id=since
            )
        else:
            raise Exception("Unknown timeline to fetch!")

        return cast(List[Dict[str, Any]], statuses)

    def getAccountInfo(self, accountID: Optional[int] = None) -> Dict[str, Any]:
        self.__assert_valid()

        if accountID:
            return cast(Dict[str, Any], self.__client.account(accountID))
        else:
            return cast(Dict[str, Any], self.__client.me())

    def createPost(
        self, status: str, visibility: Visibility, *, cw: Optional[str] = None
    ) -> Dict[str, Any]:
        self.__assert_valid()

        if visibility == Visibility.PUBLIC:
            visStr = "public"
        elif visibility == Visibility.UNLISTED:
            visStr = "unlisted"
        elif visibility == Visibility.PRIVATE:
            visStr = "private"
        elif visibility == Visibility.DIRECT:
            visStr = "direct"
        else:
            raise Exception("Unknown post visibility!")

        return cast(
            Dict[str, Any],
            self.__client.status_post(status, visibility=visStr, spoiler_text=cw),
        )
