import os
from enum import Enum, auto
from mastodon import Mastodon  # type: ignore
from mastodon.errors import MastodonIllegalArgumentError  # type: ignore
from urllib.parse import urlparse
from typing import Any, Dict, List, cast


class Timeline(Enum):
    HOME = auto()


class BadLoginError(Exception):
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
        if not os.path.isfile(creds_file):
            Mastodon.create_app(
                self.CLIENT_NAME, api_base_url=server, to_file=creds_file
            )

        # Now, save the client itself.
        self.client = Mastodon(client_id=creds_file)

    def __get_client_creds_file(self, server: str) -> str:
        url = urlparse(server)
        return f"{url.hostname}.clientcred.secret"

    def login(self, username: str, password: str) -> None:
        try:
            self.client.log_in(username, password)
        except MastodonIllegalArgumentError:
            raise BadLoginError("Bad username or password!")

    def fetchTimeline(self, which: Timeline) -> List[Dict[str, Any]]:
        if which == Timeline.HOME:
            statuses = self.client.timeline(timeline="home")
        else:
            raise Exception("Unknown timeline to fetch!")

        return cast(List[Dict[str, Any]], statuses)
