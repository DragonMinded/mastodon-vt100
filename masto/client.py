import os
from datetime import datetime
from enum import Enum, auto
from mastodon import Mastodon  # type: ignore
from mastodon.errors import MastodonNetworkError, MastodonIllegalArgumentError  # type: ignore
from urllib.parse import urlparse
from typing import Dict, List, Optional, TypedDict, cast


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
    in_reply_to_id: Optional[int]
    uri: str
    url: str
    account: AccountInfoDict
    reblog: Optional["StatusDict"]
    content: str
    spoiler_text: Optional[str]
    media_attachments: List[MediaDict]
    created_at: datetime
    ancestors: List["StatusDict"]
    replies: List["StatusDict"]
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
        post = cast(StatusDict, self.__client.status(postId))
        post['ancestors'] = []
        post['replies'] = []
        return post

    def fetchPostAndRelated(self, postId: int) -> StatusDict:
        self.__assert_valid()
        post = self.fetchPost(postId)
        related = cast(RelatedDict, self.__client.status_context(postId))

        # Set some sane defaults.
        post['ancestors'] = []
        post['replies'] = []

        if related['ancestors']:
            # First, get a linked list of ancestors.
            ancestors = related['ancestors']
            for a in ancestors:
                a['replies'] = []
                a['ancestors'] = []

            # Start by grabbing the origin, which is the ancestor with no in reply ID.
            # Filter that out of the list of ancestors, and set our linked list to point at
            # the origin.
            origin: Optional[StatusDict] = [a for a in ancestors if a['in_reply_to_id'] is None][0]
            ancestors = [a for a in ancestors if a['in_reply_to_id']]
            current = origin

            while ancestors:
                if not current:
                    raise Exception("Logic error, current post is None")

                # Find the next ancestor that is in reply to the current.
                nextPosts = [a for a in ancestors if a['in_reply_to_id'] == current['id']]
                ancestors = [a for a in ancestors if a['in_reply_to_id'] != current['id']]

                if len(nextPosts) != 1:
                    raise Exception(f"Logic error, had more than one ancestor pointing at ID {current['id']}")

                nextPost = nextPosts[0]
                current['replies'] = [nextPost]
                current = nextPost

            # Now, change the linked list back into a normal list of ancestors.
            ancestors = []
            while origin:
                # Grab the current post, set the origin to the next in the linked list.
                current = origin
                origin = current['replies'][0] if current['replies'] else None

                # Sever the linked list here.
                current['ancestors'] = []
                current['replies'] = []
                ancestors.append(current)

            # Finally, update the post we're returning with the sorted list of ancestors.
            post['ancestors'] = ancestors

        if related['descendants']:
            # Sort by linked lists of replies so each direct descendant is inside the list of
            # replies of the parent post.
            posts_by_id: Dict[int, StatusDict] = {
                post['id']: post,
            }

            descendants = related['descendants']
            for d in descendants:
                d['replies'] = []
                d['ancestors'] = []

            while descendants:
                for d in descendants:
                    if d['in_reply_to_id'] is None:
                        raise Exception(f"Logic error, post ID {d['id']} should be a reply to another post")

                    if d['in_reply_to_id'] in posts_by_id:
                        # We have this reply-to's parent tracked, so add it as a child, and add it
                        # tracked.
                        posts_by_id[d['in_reply_to_id']]['replies'].append(d)
                        posts_by_id[d['id']] = d

                # Keep around only those who we didn't find a parent for this iteration.
                descendants = [d for d in descendants if d['id'] not in posts_by_id]

        return post

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
