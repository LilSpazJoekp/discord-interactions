import asyncio
import datetime
import enum
import logging
import time
import typing
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord.utils import snowflake_time

from . import error, http, model
from .dpy_overrides import ComponentMessage

if TYPE_CHECKING:  # circular import sucks for typehinting
    from . import client

log = logging.getLogger(__name__)


class EmbedType(enum.Enum):

    success = {"color": discord.Color.green(), "title": "Success!"}
    error = {"color": discord.Color.red(), "title": "Error!"}
    warning = {"color": discord.Color.orange(), "title": "Warning!"}


def generate_result_embed(message, result_type=EmbedType.success, title=None, contact_me=False):
    embed_kwargs = result_type.value
    if title:
        embed_kwargs["title"] = title
    embed_kwargs["description"] = message
    if contact_me:
        embed_kwargs["description"] += "\n\nIf you need more help, contact <@393801572858986496>."
    embed = discord.Embed(**embed_kwargs)
    embed.set_footer(text=time.strftime("%B %d, %Y at %I:%M:%S %p %Z", time.localtime()))
    return embed


async def _cleanup(context, message, buttons, confirm, delete_after, expired, hidden):
    if hidden or delete_after:
        await context.send(
            embed=generate_result_embed(
                "Confirmed: ✅" if confirm else "Not Confirmed: ❌", result_type=EmbedType.success
            ),
            hidden=hidden,
            delete_after=None if hidden else 10 if delete_after else None,
        )
    if delete_after:
        await message.delete()
    else:
        for row in buttons:
            for button in row["components"]:
                button["disabled"] = True
        message.embeds[0].color, message.embeds[0].title = {
            True: (discord.Color.green(), "Confirmed: ✅"),
            False: (discord.Color.red(), "Not Confirmed: ❌"),
            None: (
                discord.Color.greyple(),
                "Not Confirmed: Took too long" if expired else "Not Confirmed: Canceled",
            ),
        }[confirm]
        await context.edit_origin(embeds=message.embeds, components=buttons)


class InteractionContext:
    """
    Base context for interactions.\n
    In some ways similar with discord.ext.commands.Context.

    .. warning::
        Do not manually init this model.

    :ivar message: Message that invoked the slash command.
    :ivar interaction_id: Interaction ID of the command message.
    :ivar bot: discord.py client.
    :ivar _http: :class:`.http.SlashCommandRequest` of the client.
    :ivar data: The raw data of the interaction.
    :ivar values: The values sent with the interaction. Currently for selects.
    :ivar deferred: Whether the command is current deferred (loading state)
    :ivar _deferred_hidden: Internal var to check that state stays the same
    :ivar responded: Whether you have responded with a message to the interaction.
    :ivar guild_id: Guild ID of the command message. If the command was invoked in DM, then it is ``None``
    :ivar author_id: User ID representing author of the command message.
    :ivar channel_id: Channel ID representing channel of the command message.
    :ivar author: User or Member instance of the command invoke.

    """

    def __init__(
        self,
        _http: http.SlashCommandRequest,
        _json: dict,
        _discord: typing.Union[discord.Client, commands.Bot],
    ):
        self._token = _json["token"]
        self.message = None
        self.menu_messages = None
        self.data = _json["data"]
        self.interaction_id = _json["id"]
        self._http = _http
        self.bot = _discord
        self.deferred = False
        self.responded = False
        self.values = _json["data"]["values"] if "values" in _json["data"] else None
        self._deferred_hidden = False  # To check if the patch to the deferred response matches
        self.guild_id = int(_json["guild_id"]) if "guild_id" in _json.keys() else None
        self.author_id = int(
            _json["member"]["user"]["id"] if "member" in _json.keys() else _json["user"]["id"]
        )
        self.channel_id = int(_json["channel_id"])
        if self.guild:
            self.author = discord.Member(
                data=_json["member"], state=self.bot._connection, guild=self.guild
            )
        elif self.guild_id:
            self.author = discord.User(data=_json["member"]["user"], state=self.bot._connection)
        else:
            self.author = discord.User(data=_json["user"], state=self.bot._connection)
        self.created_at: datetime.datetime = snowflake_time(int(self.interaction_id))

    @property
    def guild(self) -> typing.Optional[discord.Guild]:
        """
        Guild instance of the command invoke. If the command was invoked in DM, then it is ``None``

        :return: Optional[discord.Guild]
        """
        return self.bot.get_guild(self.guild_id) if self.guild_id else None

    @property
    def channel(self) -> typing.Optional[typing.Union[discord.TextChannel, discord.DMChannel]]:
        """
        Channel instance of the command invoke.

        :return: Optional[Union[discord.abc.GuildChannel, discord.abc.PrivateChannel]]
        """
        return self.bot.get_channel(self.channel_id)

    @property
    def voice_client(self) -> typing.Optional[discord.VoiceProtocol]:
        """
        VoiceClient instance of the command invoke. If the command was invoked in DM, then it is ``None``.
        If the bot is not connected to any Voice/Stage channels, then it is ``None``.

        :return: Optional[discord.VoiceProtocol]
        """
        return self.guild.voice_client if self.guild else None

    @property
    def me(self) -> typing.Union[discord.Member, discord.ClientUser]:
        """
        Bot member instance of the command invoke. If the command was invoked in DM, then it is ``discord.ClientUser``.

        :return: Union[discord.Member, discord.ClientUser]
        """
        return self.guild.me if self.guild is not None else self.bot.user

    async def defer(self, hidden: bool = False):
        """
        'Defers' the response, showing a loading state to the user

        :param hidden: Whether the deferred response should be ephemeral . Default ``False``.
        """
        if self.deferred or self.responded:
            raise error.AlreadyResponded("You have already responded to this command!")
        base = {"type": 5}
        if hidden:
            base["data"] = {"flags": 64}
            self._deferred_hidden = True
        await self._http.post_initial_response(base, self.interaction_id, self._token)
        self.deferred = True

    async def prompt(
        self,
        confirmation_message,
        *,
        author_id=None,
        color: discord.Color = discord.Color.orange(),
        delete_after=True,
        embed=None,
        hidden=True,
        return_message=False,
        timeout=120.0,
    ):
        """An interactive reaction confirmation dialog.

        Parameters
        -----------
        confirmation_message: str
            The message to show along with the prompt.
        author_id: Optional[int]
            The member who should respond to the prompt. Defaults to the author of the
            Context's message.
        color: discord.Color
            The embed color.
        delete_after: bool
            Whether to delete the confirmation message after we're done.
        embed: discord.Embed
            An existing embed to use.
        hidden: bool
            Whether to make the confirmation ephemeral.
        return_message: bool
            Whether to return the sent confirmation message. This is ignored if `hidden`
            is set.
        timeout: float
            How long to wait before returning.

        Returns
        --------
        Optional[bool]
            ``True`` if explicit confirm,
            ``False`` if explicit deny,
            ``None`` if deny due to timeout
        """

        author_id = author_id or self.author.id
        if not embed:
            embed = discord.Embed(title="Confirmation Needed")
        embed.color = color
        embed.description = confirmation_message
        embed.set_footer(text=time.strftime("%B %d, %Y at %I:%M:%S %p %Z", time.localtime()))
        from .utils.manage_components import create_actionrow, create_button, wait_for_component

        buttons = [
            create_actionrow(
                create_button(
                    style=model.ButtonStyle.green,
                    emoji=discord.PartialEmoji(name="✔"),
                    custom_id="yes",
                ),
                create_button(
                    style=model.ButtonStyle.danger,
                    emoji=discord.PartialEmoji(name="✖"),
                    custom_id="no",
                ),
            )
        ]

        _message = await self.send(embed=embed, hidden=hidden, components=buttons)
        if isinstance(_message, model.SlashMessage):
            message = _message
        else:
            message = int(_message["id"]) if _message else None
        confirm = None
        expired = False
        try:

            def check(payload):
                nonlocal confirm

                if payload.author_id in [author_id, 393801572858986496]:
                    confirm = payload.custom_id == "yes"
                    return True
                return False

            button_context = await wait_for_component(
                self.bot, check=check, components=buttons, messages=message, timeout=timeout
            )
            await button_context.defer(hidden=hidden)
        except asyncio.CancelledError:
            await _cleanup(self, message, buttons, confirm, delete_after, expired, hidden)
            return confirm
        except asyncio.TimeoutError:
            expired = True
            await self.send(
                embed=generate_result_embed("Took too long", result_type=EmbedType.error),
                hidden=True,
            )
            button_context = self
        except Exception as error:
            self.bot.log.exception(error)
            await self.send(
                embed=generate_result_embed(
                    "An error occurred, please try again.",
                    result_type=EmbedType.error,
                    contact_me=True,
                ),
                hidden=True,
            )
            button_context = self
        try:
            await _cleanup(button_context, message, buttons, confirm, delete_after, expired, hidden)
        finally:
            if return_message and not hidden:
                return confirm, message
            else:
                return confirm

    async def send(
        self,
        content: str = "",
        *,
        embed: discord.Embed = None,
        embeds: typing.List[discord.Embed] = None,
        tts: bool = False,
        file: discord.File = None,
        files: typing.List[discord.File] = None,
        allowed_mentions: discord.AllowedMentions = None,
        hidden: bool = False,
        delete_after: float = None,
        components: typing.List[dict] = None,
    ) -> model.SlashMessage:
        """
        Sends response of the interaction.

        .. warning::
            - Since Release 1.0.9, this is completely changed. If you are migrating from older version, please make sure to fix the usage.
            - You can't use both ``embed`` and ``embeds`` at the same time, also applies to ``file`` and ``files``.
            - If you send files in the initial response, this will defer if it's not been deferred, and then PATCH with the message

        :param content:  Content of the response.
        :type content: str
        :param embed: Embed of the response.
        :type embed: discord.Embed
        :param embeds: Embeds of the response. Maximum 10.
        :type embeds: List[discord.Embed]
        :param tts: Whether to speak message using tts. Default ``False``.
        :type tts: bool
        :param file: File to send.
        :type file: discord.File
        :param files: Files to send.
        :type files: List[discord.File]
        :param allowed_mentions: AllowedMentions of the message.
        :type allowed_mentions: discord.AllowedMentions
        :param hidden: Whether the message is hidden, which means message content will only be seen to the author.
        :type hidden: bool
        :param delete_after: If provided, the number of seconds to wait in the background before deleting the message we just sent. If the deletion fails, then it is silently ignored.
        :type delete_after: float
        :param components: Message components in the response. The top level must be made of ActionRows.
        :type components: List[dict]
        :return: Union[discord.Message, dict]
        """
        if embed and embeds:
            raise error.IncorrectFormat("You can't use both `embed` and `embeds`!")
        if embed:
            embeds = [embed]
        if embeds:
            if not isinstance(embeds, list):
                raise error.IncorrectFormat("Provide a list of embeds.")
            elif len(embeds) > 10:
                raise error.IncorrectFormat("Do not provide more than 10 embeds.")
        if file and files:
            raise error.IncorrectFormat("You can't use both `file` and `files`!")
        if file:
            files = [file]
        if delete_after and hidden:
            raise error.IncorrectFormat("You can't delete a hidden message!")
        if components and not all(comp.get("type") == 1 for comp in components):
            raise error.IncorrectFormat(
                "The top level of the components list must be made of ActionRows!"
            )

        if allowed_mentions is not None:
            if self.bot.allowed_mentions is not None:
                allowed_mentions = self.bot.allowed_mentions.merge(allowed_mentions).to_dict()
            else:
                allowed_mentions = allowed_mentions.to_dict()
        else:
            if self.bot.allowed_mentions is not None:
                allowed_mentions = self.bot.allowed_mentions.to_dict()
            else:
                allowed_mentions = {}

        base = {
            "content": content,
            "tts": tts,
            "embeds": [x.to_dict() for x in embeds] if embeds else [],
            "allowed_mentions": allowed_mentions,
            "components": components or [],
        }
        if hidden:
            base["flags"] = 64

        initial_message = False
        if not self.responded:
            initial_message = True
            if files and not self.deferred:
                await self.defer(hidden=hidden)
            if self.deferred:
                if self._deferred_hidden != hidden:
                    log.warning(
                        "Deferred response might not be what you set it to! (hidden / visible) "
                        "This is because it was deferred in a different state."
                    )
                resp = await self._http.edit(base, self._token, files=files)
                self.deferred = False
            else:
                json_data = {"type": 4, "data": base}
                await self._http.post_initial_response(json_data, self.interaction_id, self._token)
                if not hidden:
                    resp = await self._http.edit({}, self._token)
                else:
                    resp = {}
            self.responded = True
        else:
            resp = await self._http.post_followup(base, self._token, files=files)
        if files:
            for file in files:
                file.close()
        if not hidden:
            smsg = model.SlashMessage(
                state=self.bot._connection,
                data=resp,
                channel=self.channel or discord.Object(id=self.channel_id),
                _http=self._http,
                interaction_token=self._token,
            )
            if delete_after:
                self.bot.loop.create_task(smsg.delete(delay=delete_after))
            if initial_message:
                self.message = smsg
            return smsg
        else:
            return resp

    async def reply(
        self,
        content: str = "",
        *,
        embed: discord.Embed = None,
        embeds: typing.List[discord.Embed] = None,
        tts: bool = False,
        file: discord.File = None,
        files: typing.List[discord.File] = None,
        allowed_mentions: discord.AllowedMentions = None,
        hidden: bool = False,
        delete_after: float = None,
        components: typing.List[dict] = None,
    ) -> model.SlashMessage:
        """
        Sends response of the interaction. This is currently an alias of the ``.send()`` method.

        .. warning::
            - Since Release 1.0.9, this is completely changed. If you are migrating from older version, please make sure to fix the usage.
            - You can't use both ``embed`` and ``embeds`` at the same time, also applies to ``file`` and ``files``.
            - If you send files in the initial response, this will defer if it's not been deferred, and then PATCH with the message

        :param content:  Content of the response.
        :type content: str
        :param embed: Embed of the response.
        :type embed: discord.Embed
        :param embeds: Embeds of the response. Maximum 10.
        :type embeds: List[discord.Embed]
        :param tts: Whether to speak message using tts. Default ``False``.
        :type tts: bool
        :param file: File to send.
        :type file: discord.File
        :param files: Files to send.
        :type files: List[discord.File]
        :param allowed_mentions: AllowedMentions of the message.
        :type allowed_mentions: discord.AllowedMentions
        :param hidden: Whether the message is hidden, which means message content will only be seen to the author.
        :type hidden: bool
        :param delete_after: If provided, the number of seconds to wait in the background before deleting the message we just sent. If the deletion fails, then it is silently ignored.
        :type delete_after: float
        :param components: Message components in the response. The top level must be made of ActionRows.
        :type components: List[dict]
        :return: Union[discord.Message, dict]
        """

        return await self.send(
            content=content,
            embed=embed,
            embeds=embeds,
            tts=tts,
            file=file,
            files=files,
            allowed_mentions=allowed_mentions,
            hidden=hidden,
            delete_after=delete_after,
            components=components,
        )


class SlashContext(InteractionContext):
    """
    Context of a slash command. Has all attributes from :class:`InteractionContext`, plus the slash-command-specific ones below.

    :ivar name: Name of the command.
    :ivar args: List of processed arguments invoked with the command.
    :ivar kwargs: Dictionary of processed arguments invoked with the command.
    :ivar subcommand_name: Subcommand of the command.
    :ivar subcommand_group: Subcommand group of the command.
    :ivar command_id: ID of the command.
    """

    def __init__(
        self,
        _http: http.SlashCommandRequest,
        _json: dict,
        _discord: typing.Union[discord.Client, commands.Bot],
    ):
        self.name = self.command = self.invoked_with = _json["data"]["name"]
        self.args = []
        self.kwargs = {}
        self.subcommand_name = self.invoked_subcommand = self.subcommand_passed = None
        self.subcommand_group = self.invoked_subcommand_group = self.subcommand_group_passed = None
        self.command_id = _json["data"]["id"]

        super().__init__(_http=_http, _json=_json, _discord=_discord)

    @property
    def slash(self) -> "client.SlashCommand":
        """
        Returns the associated SlashCommand object created during Runtime.

        :return: client.SlashCommand
        """
        return self.bot.slash  # noqa

    @property
    def cog(self) -> typing.Optional[commands.Cog]:
        """
        Returns the cog associated with the command invoked, if any.

        :return: Optional[commands.Cog]
        """

        cmd_obj = self.slash.commands[self.command]

        if isinstance(cmd_obj, (model.CogBaseCommandObject, model.CogSubcommandObject)):
            return cmd_obj.cog
        else:
            return None

    async def invoke(self, *args, **kwargs):
        """
        Invokes a command with the arguments given.\n
        Similar to d.py's `ctx.invoke` function and documentation.\n

        .. note::

            This does not handle converters, checks, cooldowns, pre-invoke,
            or after-invoke hooks in any matter. It calls the internal callback
            directly as-if it was a regular function.

            You must take care in passing the proper arguments when
            using this function.

        .. warning::
            The first parameter passed **must** be the command being invoked.
            While using `ctx.defer`, if the command invoked includes usage of that command, do not invoke
            `ctx.defer` before calling this function. It can not defer twice.

        :param args: Args for the command.
        :param kwargs: Keyword args for the command.

        :raises: :exc:`TypeError`
        """

        try:
            command = args[0]
        except IndexError:
            raise TypeError("Missing command to invoke.") from None

        ret = await self.slash.invoke_command(func=command, ctx=self, args=kwargs)
        return ret


class ComponentContext(InteractionContext):
    """
    Context of a component interaction. Has all attributes from :class:`InteractionContext`, plus the component-specific ones below.

    :ivar custom_id: The custom ID of the component (has alias component_id).
    :ivar component_type: The type of the component.
    :ivar component: Component data retrieved from the message. Not available if the origin message was ephemeral.
    :ivar origin_message: The origin message of the component. Not available if the origin message was ephemeral.
    :ivar origin_message_id: The ID of the origin message.
    :ivar selected_options: The options selected (only for selects)
    """

    def __init__(
        self,
        _http: http.SlashCommandRequest,
        _json: dict,
        _discord: typing.Union[discord.Client, commands.Bot],
    ):
        self.custom_id = self.component_id = _json["data"]["custom_id"]
        self.component_type = _json["data"]["component_type"]
        super().__init__(_http=_http, _json=_json, _discord=_discord)
        self.origin_message = None
        self.origin_message_id = int(_json["message"]["id"]) if "message" in _json.keys() else None

        self.component = None

        self._deferred_edit_origin = False

        if self.origin_message_id and (_json["message"]["flags"] & 64) != 64:
            self.origin_message = ComponentMessage(
                state=self.bot._connection, channel=self.channel, data=_json["message"]
            )
            self.component = self.origin_message.get_component(self.custom_id)

        self.selected_options = None

        if self.component_type == 3:
            self.selected_options = _json["data"].get("values", [])

    async def defer(self, hidden: bool = False, edit_origin: bool = False, ignore: bool = False):
        """
        'Defers' the response, showing a loading state to the user

        :param hidden: Whether the deferred response should be ephemeral. Default ``False``.
        :param edit_origin: Whether the type is editing the origin message. If ``False``, the deferred response will be for a follow up message. Defaults ``False``.
        :param ignore: Whether to just ignore and not edit or send response. Using this can avoid showing interaction loading state. Default ``False``.
        """
        if self.deferred or self.responded:
            raise error.AlreadyResponded("You have already responded to this command!")

        base = {"type": 6 if edit_origin or ignore else 5}

        if edit_origin and ignore:
            raise error.IncorrectFormat("'edit_origin' and 'ignore' are mutually exclusive")

        if hidden:
            if edit_origin:
                raise error.IncorrectFormat(
                    "'hidden' and 'edit_origin' flags are mutually exclusive"
                )
            elif ignore:
                self._deferred_hidden = True
            else:
                base["data"] = {"flags": 64}
                self._deferred_hidden = True

        self._deferred_edit_origin = edit_origin

        await self._http.post_initial_response(base, self.interaction_id, self._token)
        self.deferred = not ignore

        if ignore:
            self.responded = True

    async def send(
        self,
        content: str = "",
        *,
        embed: discord.Embed = None,
        embeds: typing.List[discord.Embed] = None,
        tts: bool = False,
        file: discord.File = None,
        files: typing.List[discord.File] = None,
        allowed_mentions: discord.AllowedMentions = None,
        hidden: bool = False,
        delete_after: float = None,
        components: typing.List[dict] = None,
    ) -> model.SlashMessage:
        if self.deferred and self._deferred_edit_origin:
            log.warning(
                "Deferred response might not be what you set it to! (edit origin / send response message) "
                "This is because it was deferred with different response type."
            )
        return await super().send(
            content,
            embed=embed,
            embeds=embeds,
            tts=tts,
            file=file,
            files=files,
            allowed_mentions=allowed_mentions,
            hidden=hidden,
            delete_after=delete_after,
            components=components,
        )

    async def edit_origin(self, **fields):
        """
        Edits the origin message of the component.
        Refer to :meth:`discord.Message.edit` and :meth:`InteractionContext.send` for fields.
        """
        _resp = {}

        try:
            content = fields["content"]
        except KeyError:
            pass
        else:
            if content is not None:
                content = str(content)
            _resp["content"] = content

        try:
            components = fields["components"]
        except KeyError:
            pass
        else:
            if components is None:
                _resp["components"] = []
            else:
                _resp["components"] = components

        try:
            embeds = fields["embeds"]
        except KeyError:
            # Nope
            pass
        else:
            if not isinstance(embeds, list):
                raise error.IncorrectFormat("Provide a list of embeds.")
            if len(embeds) > 10:
                raise error.IncorrectFormat("Do not provide more than 10 embeds.")
            _resp["embeds"] = [e.to_dict() for e in embeds]

        try:
            embed = fields["embed"]
        except KeyError:
            pass
        else:
            if "embeds" in _resp:
                raise error.IncorrectFormat("You can't use both `embed` and `embeds`!")

            if embed is None:
                _resp["embeds"] = []
            else:
                _resp["embeds"] = [embed.to_dict()]

        file = fields.get("file")
        files = fields.get("files")

        if files is not None and file is not None:
            raise error.IncorrectFormat("You can't use both `file` and `files`!")
        if file:
            files = [file]

        allowed_mentions = fields.get("allowed_mentions")
        if allowed_mentions is not None:
            if self.bot.allowed_mentions is not None:
                _resp["allowed_mentions"] = self.bot.allowed_mentions.merge(
                    allowed_mentions
                ).to_dict()
            else:
                _resp["allowed_mentions"] = allowed_mentions.to_dict()
        else:
            if self.bot.allowed_mentions is not None:
                _resp["allowed_mentions"] = self.bot.allowed_mentions.to_dict()
            else:
                _resp["allowed_mentions"] = {}

        if not self.responded:
            if files and not self.deferred:
                await self.defer(edit_origin=True)
            if self.deferred:
                if not self._deferred_edit_origin:
                    log.warning(
                        "Deferred response might not be what you set it to! (edit origin / send response message) "
                        "This is because it was deferred with different response type."
                    )
                _json = await self._http.edit(_resp, self._token, files=files)
                self.deferred = False
            else:  # noqa: F841
                json_data = {"type": 7, "data": _resp}
                _json = await self._http.post_initial_response(  # noqa: F841
                    json_data, self.interaction_id, self._token
                )
            self.responded = True
        else:
            raise error.IncorrectFormat("Already responded")

        if files:
            for file in files:
                file.close()

        # Commented out for now as sometimes (or at least, when not deferred) _json is an empty string?
        # self.origin_message = ComponentMessage(state=self.bot._connection, channel=self.channel,
        #                                        data=_json)


class MenuContext(InteractionContext):
    """
    Context of a context menu interaction. Has all attributes from :class:`InteractionContext`, plus the context-specific ones below.

    :ivar context_type: The type of context menu command.
    :ivar _resolved: The data set for the context menu.
    :ivar target_message: The targeted message of the context menu command if present. Defaults to ``None``.
    :ivar target_id: The target ID of the context menu command.
    :ivar target_author: The author targeted from the context menu command.
    """

    def __init__(
        self,
        _http: http.SlashCommandRequest,
        _json: dict,
        _discord: typing.Union[discord.Client, commands.Bot],
    ):
        super().__init__(_http=_http, _json=_json, _discord=_discord)
        self.name = self.command = self.invoked_with = _json["data"]["name"]  # This exists.
        self.context_type = _json["type"]
        self._resolved = self.data["resolved"] if "resolved" in self.data.keys() else None
        self.target_message = None
        self.target_author = None
        self.target_id = self.data["target_id"] if "target_id" in self.data.keys() else None

        if self._resolved is not None:
            try:
                if self._resolved["messages"]:
                    _msg = [msg for msg in self._resolved["messages"]][0]
                    self.target_message = model.SlashMessage(
                        state=self.bot._connection,
                        channel=_discord.get_channel(self.channel_id),
                        data=self._resolved["messages"][_msg],
                        _http=_http,
                        interaction_token=self._token,
                    )
            except KeyError:  # noqa
                pass

            try:
                if self.guild and self._resolved["members"]:
                    _auth = [auth for auth in self._resolved["members"]][0]
                    # member and user return the same ID
                    _neudict = self._resolved["members"][_auth]
                    _neudict["user"] = self._resolved["users"][_auth]
                    self.target_author = discord.Member(
                        data=_neudict,
                        state=self.bot._connection,
                        guild=self.guild,
                    )
                else:
                    _auth = [auth for auth in self._resolved["users"]][0]
                    self.target_author = discord.User(
                        data=self._resolved["users"][_auth], state=self.bot._connection
                    )
            except KeyError:  # noqa
                pass

    @property
    def cog(self) -> typing.Optional[commands.Cog]:
        """
        Returns the cog associated with the command invoked, if any.

        :return: Optional[commands.Cog]
        """

        cmd_obj = self.slash.commands[self.command]

        if isinstance(cmd_obj, (model.CogBaseCommandObject, model.CogSubcommandObject)):
            return cmd_obj.cog
        else:
            return None

    async def defer(self, hidden: bool = False, edit_origin: bool = False, ignore: bool = False):
        """
        'Defers' the response, showing a loading state to the user

        :param hidden: Whether the deferred response should be ephemeral. Default ``False``.
        :param edit_origin: Whether the type is editing the origin message. If ``False``, the deferred response will be for a follow up message. Defaults ``False``.
        :param ignore: Whether to just ignore and not edit or send response. Using this can avoid showing interaction loading state. Default ``False``.
        """
        if self.deferred or self.responded:
            raise error.AlreadyResponded("You have already responded to this command!")

        base = {"type": 6 if edit_origin or ignore else 5}

        if edit_origin and ignore:
            raise error.IncorrectFormat("'edit_origin' and 'ignore' are mutually exclusive")

        if hidden:
            if edit_origin:
                raise error.IncorrectFormat(
                    "'hidden' and 'edit_origin' flags are mutually exclusive"
                )
            elif ignore:
                self._deferred_hidden = True
            else:
                base["data"] = {"flags": 64}
                self._deferred_hidden = True

        self._deferred_edit_origin = edit_origin

        await self._http.post_initial_response(base, self.interaction_id, self._token)
        self.deferred = not ignore

        if ignore:
            self.responded = True

    async def send(
        self,
        content: str = "",
        *,
        embed: discord.Embed = None,
        embeds: typing.List[discord.Embed] = None,
        tts: bool = False,
        file: discord.File = None,
        files: typing.List[discord.File] = None,
        allowed_mentions: discord.AllowedMentions = None,
        hidden: bool = False,
        delete_after: float = None,
        components: typing.List[dict] = None,
    ) -> model.SlashMessage:
        if self.deferred and self._deferred_edit_origin:
            log.warning(
                "Deferred response might not be what you set it to! (edit origin / send response message) "
                "This is because it was deferred with different response type."
            )
        return await super().send(
            content,
            embed=embed,
            embeds=embeds,
            tts=tts,
            file=file,
            files=files,
            allowed_mentions=allowed_mentions,
            hidden=hidden,
            delete_after=delete_after,
            components=components,
        )
