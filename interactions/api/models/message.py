from datetime import datetime
from enum import IntEnum
from typing import List, Optional, Union

from .member import Member
from .team import Application
from .user import User


class MessageType(IntEnum):
    """
    Type of messages.

    ..note::
        While all of them are listed, not all of them would be used at this lib's scope.
    """

    DEFAULT = 0
    RECIPIENT_ADD = 1
    RECIPIENT_REMOVE = 2
    CALL = 3
    CHANNEL_NAME_CHANGE = 4
    CHANNEL_ICON_CHANGE = 5
    CHANNEL_PINNED_MESSAGE = 6
    GUILD_MEMBER_JOIN = 7
    USER_PREMIUM_GUILD_SUBSCRIPTION = 8
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_1 = 9
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_2 = 10
    USER_PREMIUM_GUILD_SUBSCRIPTION_TIER_3 = 11
    CHANNEL_FOLLOW_ADD = 12
    GUILD_DISCOVERY_DISQUALIFIED = 14
    GUILD_DISCOVERY_REQUALIFIED = 15
    GUILD_DISCOVERY_GRACE_PERIOD_INITIAL_WARNING = 16
    GUILD_DISCOVERY_GRACE_PERIOD_FINAL_WARNING = 17
    THREAD_CREATED = 18
    REPLY = 19
    APPLICATION_COMMAND = 20
    THREAD_STARTER_MESSAGE = 21
    GUILD_INVITE_REMINDER = 22


class MessageActivity(object):
    __slots__ = ("type", "party_id")
    type: int
    party_id: Optional[str]


class MessageReference(object):
    __slots__ = ("message_id", "channel_id", "guild_id", "fail_if_not_exists")
    message_id: Optional[int]
    channel_id: Optional[int]
    guild_id: Optional[int]
    fail_if_not_exists: Optional[bool]


class Attachment(object):
    __slots__ = ("id", "filename", "content_type", "size", "url", "proxy_url", "height", "width")

    id: int
    filename: str
    content_type: Optional[str]
    size: int
    url: str
    proxy_url: str
    height: Optional[int]
    width: Optional[int]


class MessageInteraction(object):
    id: int
    type: int  # replace with Enum
    name: str
    user: User


class ChannelMention(object):
    id: int
    guild_id: int
    type: int  # Replace with enum from Channel Type, another PR
    name: str


class Message(object):
    """
    The big Message model.

    The purpose of this model is to be used as a base class, and
    is never needed to be used directly.
    """

    id: int
    channel_id: int
    guild_id: Optional[int]
    author: User
    member: Optional[Member]
    content: str
    timestamp: datetime.timestamp
    edited_timestamp: Optional[datetime]
    tts: bool
    mention_everyone: bool
    # mentions: array of Users, and maybe partial members
    mentions: Optional[List[Union[Member, User]]]
    mention_roles: Optional[List[str]]
    mention_channels: Optional[List["ChannelMention"]]
    attachments: Optional[List[Attachment]]
    embeds: List["Embed"]
    reactions: Optional[List["ReactionObject"]]
    nonce: Union[int, str]
    pinned: bool
    webhook_id: Optional[int]
    type: int
    activity: Optional[MessageActivity]
    application: Optional[Application]
    application_id: int
    message_reference: Optional[MessageReference]
    flags: int
    referenced_message: Optional["Message"]  # pycharm says it works, idk
    interaction: Optional[MessageInteraction]
    thread: Optional[ChannelMention]

    # components (Flow's side)
    sticker_items: Optional[List["PartialSticker"]]
    stickers: Optional[List["Sticker"]]  # deprecated

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class Emoji(object):
    id: Optional[int]
    name: Optional[str]
    roles: Optional[List[str]]
    user: Optional[User]
    require_colons: Optional[bool]
    managed: Optional[bool]
    animated: Optional[bool]
    available: Optional[bool]

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ReactionObject(object):
    count: int
    me: bool
    emoji: Emoji


class PartialSticker(object):
    """Partial object for a Sticker."""

    id: int
    name: str
    format_type: int


class Sticker(PartialSticker):
    """The full Sticker object."""

    pack_id: Optional[int]
    description: Optional[str]
    tags: str
    asset: str  # deprecated
    type: int  # has its own dedicated enum
    available: Optional[bool]
    guild_id: Optional[int]
    user: Optional[User]
    sort_value: Optional[int]


class EmbedImageStruct(object):
    """This is the internal structure denoted for thumbnails, images or videos"""

    url: Optional[str]
    proxy_url: Optional[str]
    height: Optional[str]
    width: Optional[str]


class EmbedProvider(object):
    name: Optional[str]
    url: Optional[str]


class EmbedAuthor(object):
    name: Optional[str]
    url: Optional[str]
    icon_url: Optional[str]
    proxy_icon_url: Optional[str]


class EmbedFooter(object):
    text: Optional[str]
    icon_url: Optional[str]
    proxy_icon_url: Optional[str]


class EmbedField(object):
    name: str
    inline: Optional[bool]
    value: str


class Embed(object):
    title: Optional[str]
    type: Optional[str]
    description: Optional[str]
    url: Optional[str]
    timestamp: Optional[datetime]
    color: Optional[int]
    footer: Optional[EmbedFooter]
    image: Optional[EmbedImageStruct]
    thumbnail: Optional[EmbedImageStruct]
    video: Optional[EmbedImageStruct]
    provider: Optional[EmbedProvider]
    author: Optional[EmbedAuthor]
    fields: Optional[List[EmbedField]]