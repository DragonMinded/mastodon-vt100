import os
from datetime import datetime
from enum import Enum, auto
from mastodon import Mastodon  # type: ignore
from mastodon.errors import MastodonNetworkError, MastodonIllegalArgumentError  # type: ignore
from urllib.parse import urlparse
from typing import List, Optional, TypedDict, cast


class Timeline(Enum):
    HOME = auto()
    LOCAL = auto()
    PUBLIC = auto()


class Visibility(Enum):
    PUBLIC = auto()
    UNLISTED = auto()
    PRIVATE = auto()
    DIRECT = auto()


class BadLoginError(Exception):
    pass


class InvalidClientError(Exception):
    pass


PreferencesDict = TypedDict(
    'PreferencesDict',
    # Based on mastodon.py documentation and printing the contents from my local
    # mastodon server.
    {
        'posting:default:language': str,
        'posting:default:sensitive': bool,
        'posting:default:visibility': str,
        'reading:autoplay:gifs': bool,
        'reading:expand:media': str,
        'reading:expand:spoilers': bool,
    },
)


class AccountInfoDict(TypedDict):
    # Incomplete, there's a ton more on mastodon.py that I haven't put here yet.
    id: int
    username: str
    acct: str
    display_name: str


class MediaDict(TypedDict):
    # Incomplete, there's a ton more on mastodon.py that I haven't put here yet.
    id: int
    type: str
    url: str
    description: Optional[str]


class StatusDict(TypedDict):
    # Incomplete, there's a ton more on mastodon.py that I haven't put here yet.
    id: int
    uri: str
    url: str
    account: AccountInfoDict
    reblog: Optional["StatusDict"]
    content: str
    spoiler_text: Optional[str]
    media_attachments: List[MediaDict]
    created_at: datetime
    replies_count: int
    reblogs_count: int
    favourites_count: int
    favourited: bool
    reblogged: bool
    muted: bool
    bookmarked: bool


class RelatedDict(TypedDict):
    ancestors: List[StatusDict]
    descendants: List[StatusDict]


class Client:
    SECRETS_LOC: str = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "secrets")
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
        since: Optional[StatusDict] = None,
    ) -> List[StatusDict]:
        self.__assert_valid()

        if which == Timeline.HOME:
            statuses = self.__client.timeline(
                timeline="home", limit=limit, max_id=since
            )
        elif which == Timeline.LOCAL:
            statuses = self.__client.timeline(
                timeline="local", limit=limit, max_id=since
            )
        elif which == Timeline.PUBLIC:
            statuses = self.__client.timeline(
                timeline="public", limit=limit, max_id=since
            )
        else:
            raise Exception("Unknown timeline to fetch!")

        return cast(List[StatusDict], statuses)

    def fetchPost(self, postId: int) -> StatusDict:
        self.__assert_valid()
        return cast(StatusDict, self.__client.status(postId))

    def fetchRelated(self, postId: int) -> RelatedDict:
        self.__assert_valid()
        return cast(RelatedDict, self.__client.status_context(postId))

    def getPreferences(self) -> PreferencesDict:
        self.__assert_valid()
        return cast(PreferencesDict, self.__client.preferences())

    def getAccountInfo(self, accountID: Optional[int] = None) -> AccountInfoDict:
        self.__assert_valid()

        if accountID:
            return cast(AccountInfoDict, self.__client.account(accountID))
        else:
            return cast(AccountInfoDict, self.__client.me())

    def createPost(
        self, status: str, visibility: Visibility, *, cw: Optional[str] = None
    ) -> StatusDict:
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
            StatusDict,
            self.__client.status_post(status, visibility=visStr, spoiler_text=cw),
        )
