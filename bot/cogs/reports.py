import json
import logging
import re
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.db import Database
from bot.defang import defang_text
from bot.moderation import try_delete_message


_MESSAGE_LINK_RE = re.compile(
    r"https?://(?:canary\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


def _parse_message_link(link: str) -> Optional[tuple[int, int, int]]:
    match = _MESSAGE_LINK_RE.fullmatch(link.strip())
    logger.debug("_parse_message_link: link=%s match=%s", link, match)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _sanitize_mentions(text: str) -> str:
    if not text:
        return text
    return discord.utils.escape_mentions(text)


async def _get_safe_files(attachments: list[discord.Attachment]) -> list[discord.File]:
    ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
    MAX_FILE_SIZE = 8 * 1024 * 1024

    safe_files = []
    for attachment in attachments:
        ext = "." + attachment.filename.rsplit(".", 1)[-1].lower() if "." in attachment.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            continue
        if attachment.size > MAX_FILE_SIZE:
            continue
        try:
            safe_files.append(await attachment.to_file())
        except (discord.HTTPException, discord.Forbidden):
            continue
    return safe_files


class ReportReviewView(discord.ui.View):
    def __init__(self, bot: commands.Bot, config: Config, db: Database, report_id: int) -> None:
        super().__init__(timeout=7 * 24 * 60 * 60)
        self.bot = bot
        self.config = config
        self.db = db
        self.report_id = report_id

    def _has_permission(self, interaction: discord.Interaction) -> bool:
        perms = interaction.user.guild_permissions
        return perms.administrator or perms.manage_messages

    async def _ban_author(self, interaction: discord.Interaction, author_id: int) -> bool:
        try:
            await interaction.guild.ban(
                discord.Object(id=author_id),
                reason="Ban Hammer Bot",
            )
            return True
        except (discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "Failed to ban author_id=%s guild_id=%s error=%s",
                author_id,
                interaction.guild.id if interaction.guild else None,
                exc,
            )
            return False

    def _with_action_line(self, content: str, action_line: str) -> str:
        lines = [line for line in content.split("\n") if not line.startswith("Action:")]
        lines.append(action_line)
        return "\n".join(lines)

    def _mark_action(self, action: str) -> None:
        for child in self.children:
            if not isinstance(child, discord.ui.Button):
                continue
            label = child.label or ""
            base = label.replace("✅ ", "")
            if base.lower().startswith(action):
                child.label = f"✅ {base}"
                child.disabled = True
            else:
                child.disabled = True

    @discord.ui.button(label="Remove", style=discord.ButtonStyle.danger)
    async def remove_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not self._has_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to approve reports.", ephemeral=True
            )
            return

        report = await self.db.fetch_report(self.report_id)
        if not report or report.status != "pending":
            await interaction.response.send_message(
                "This report is no longer pending.", ephemeral=True
            )
            return

        original_message = None
        try:
            channel = interaction.guild.get_channel_or_thread(report.channel_id)
            if channel:
                original_message = await channel.fetch_message(report.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "Approve fetch failed: channel_id=%s message_id=%s error=%s",
                report.channel_id,
                report.message_id,
                exc,
            )
            original_message = None

        deleted = False
        if original_message:
            deleted = await try_delete_message(original_message)

        now = int(time.time())
        await self.db.execute(
            """
            UPDATE reports
            SET status = ?, hidden = ?, resolved_at = ?
            WHERE report_id = ?
            """,
            ("removed", 1 if deleted else 0, now, report.report_id),
        )
        await self.db.execute(
            """
            INSERT INTO report_audit (report_id, action, actor_id, timestamp, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report.report_id, "removed", interaction.user.id, now, None),
        )

        ban_ok = await self._ban_author(interaction, report.author_id)

        self._mark_action("remove")
        action_line = f"Action: Remove by {interaction.user.mention}"
        updated = self._with_action_line(interaction.message.content or "", action_line)
        await interaction.response.edit_message(
            content=updated,
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        followup = "Message removed."
        if ban_ok:
            followup += " Author banned."
        else:
            followup += " Author ban failed."
        await interaction.followup.send(followup, ephemeral=True)

    @discord.ui.button(label="Wall of Shame", style=discord.ButtonStyle.primary)
    async def wall_of_shame_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not self._has_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to approve reports.", ephemeral=True
            )
            return

        report = await self.db.fetch_report(self.report_id)
        if not report or report.status != "pending":
            await interaction.response.send_message(
                "This report is no longer pending.", ephemeral=True
            )
            return

        wall_channel = interaction.guild.get_channel(self.config.wall_of_shame_channel_id)
        if not wall_channel:
            await interaction.response.send_message(
                "Wall of shame channel not found.", ephemeral=True
            )
            return

        original_message = None
        try:
            channel = interaction.guild.get_channel_or_thread(report.channel_id)
            if channel:
                original_message = await channel.fetch_message(report.message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            logger.warning(
                "Wall-of-shame fetch failed: channel_id=%s message_id=%s error=%s",
                report.channel_id,
                report.message_id,
                exc,
            )
            original_message = None

        sanitized = defang_text(report.message_content or "")
        sanitized = _sanitize_mentions(sanitized)
        files = await _get_safe_files(original_message.attachments) if original_message else []

        count_row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM reports WHERE status IN (?, ?)",
            ("removed", "wall_of_shame"),
        )
        total_bans = int(count_row["total"]) + 1 if count_row else 1

        safe_author = _sanitize_mentions(report.author_tag)
        content_lines = [
            f"{safe_author} received :hammer:THE BAN HAMMER:hammer:",
            f"**Ban Hammers Dropped: {total_bans}**",
            "---",
            sanitized or "(no content)",
            "---",
            "https://tenor.com/view/hammer-gif-23464742",
        ]
        await wall_channel.send(
            content="\n".join(content_lines),
            files=files or None,
        )

        deleted = False
        if original_message:
            deleted = await try_delete_message(original_message)

        now = int(time.time())
        await self.db.execute(
            """
            UPDATE reports
            SET status = ?, hidden = ?, resolved_at = ?
            WHERE report_id = ?
            """,
            ("wall_of_shame", 1 if deleted else 0, now, report.report_id),
        )
        await self.db.execute(
            """
            INSERT INTO report_audit (report_id, action, actor_id, timestamp, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report.report_id, "wall_of_shame", interaction.user.id, now, None),
        )

        ban_ok = await self._ban_author(interaction, report.author_id)

        self._mark_action("wall of shame")
        action_line = f"Action: Wall of Shame by {interaction.user.mention}"
        updated = self._with_action_line(interaction.message.content or "", action_line)
        await interaction.response.edit_message(
            content=updated,
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        followup = "Posted to wall of shame."
        if ban_ok:
            followup += " Author banned."
        else:
            followup += " Author ban failed."
        await interaction.followup.send(followup, ephemeral=True)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.secondary)
    async def deny_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        if not self._has_permission(interaction):
            await interaction.response.send_message(
                "You do not have permission to deny reports.", ephemeral=True
            )
            return

        report = await self.db.fetch_report(self.report_id)
        if not report or report.status != "pending":
            await interaction.response.send_message(
                "This report is no longer pending.", ephemeral=True
            )
            return

        now = int(time.time())
        await self.db.execute(
            """
            UPDATE reports
            SET status = ?, resolved_at = ?
            WHERE report_id = ?
            """,
            ("denied", now, report.report_id),
        )
        await self.db.execute(
            """
            INSERT INTO report_audit (report_id, action, actor_id, timestamp, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report.report_id, "denied", interaction.user.id, now, None),
        )

        self._mark_action("deny")
        action_line = f"Action: Deny by {interaction.user.mention}"
        updated = self._with_action_line(interaction.message.content or "", action_line)
        await interaction.response.edit_message(
            content=updated,
            view=self,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.followup.send("Report denied.", ephemeral=True)


class ReportsCog(commands.Cog):
    def __init__(self, bot: commands.Bot, config: Config, db: Database) -> None:
        self.bot = bot
        self.config = config
        self.db = db

    def _is_allowed_reporter(self, member: discord.Member) -> bool:
        if not self.config.report_role_allowlist:
            return False
        return any(
            role.id in self.config.report_role_allowlist for role in member.roles
        )

    @app_commands.command(name="report", description="Report a message for review")
    @app_commands.describe(message_link="Link to the message", reason="Reason for report")
    async def report(
        self, interaction: discord.Interaction, message_link: str, reason: str
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not isinstance(interaction.user, discord.Member) or not self._is_allowed_reporter(
            interaction.user
        ):
            await interaction.followup.send(
                "Reporting is disabled or you do not have permission.",
                ephemeral=True,
            )
            return

        parsed = _parse_message_link(message_link)
        if not parsed:
            await interaction.followup.send(
                "Invalid message link.", ephemeral=True
            )
            return

        guild_id, channel_id, message_id = parsed
        logger.info(
            "Report parsed: guild_id=%s channel_id=%s message_id=%s reporter_id=%s",
            guild_id,
            channel_id,
            message_id,
            interaction.user.id,
        )
        if interaction.guild is None or interaction.guild.id != guild_id:
            await interaction.followup.send(
                "Message must be in this server.", ephemeral=True
            )
            return

        channel = interaction.guild.get_channel_or_thread(channel_id)
        if channel is None:
            logger.info("Channel not cached, fetching channel_id=%s", channel_id)
            try:
                channel = await interaction.guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                logger.warning(
                    "Failed to fetch channel_id=%s error=%s", channel_id, exc
                )
                channel = None
        if channel is None:
            await interaction.followup.send(
                "Channel not found.", ephemeral=True
            )
            return

        try:
            message = await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError) as exc:
            logger.warning(
                "Failed to fetch message_id=%s in channel_id=%s error=%s",
                message_id,
                channel_id,
                exc,
            )
            await interaction.followup.send(
                "Unable to fetch message.", ephemeral=True
            )
            return

        logger.info(
            "Fetched message_id=%s author_id=%s channel_id=%s",
            message.id,
            message.author.id,
            channel_id,
        )

        admin_channel = interaction.guild.get_channel(self.config.admin_channel_id)
        if not admin_channel:
            await interaction.followup.send(
                "Admin channel not found.", ephemeral=True
            )
            return

        attachments = [att.url for att in message.attachments]
        message_content = defang_text(message.content) or ""
        admin_files = await _get_safe_files(message.attachments)
        now = int(time.time())
        report_id = await self.db.execute(
            """
            INSERT INTO reports
            (message_id, channel_id, guild_id, reporter_id, author_id, author_tag,
             reason, status, hidden, message_content, attachments_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                channel.id,
                interaction.guild.id,
                interaction.user.id,
                message.author.id,
                str(message.author),
                reason,
                "pending",
                0,
                message_content,
                json.dumps(attachments),
                now,
            ),
        )

        admin_lines = [
            "Message Report",
            f"Reporter: {interaction.user.mention}",
            f"Author: {message.author.mention}",
            f"Reason: {reason}",
            f"Channel: {channel.mention}",
            f"Jump Link: {message.jump_url}",
            f"Message ID: {message.id}",
            "---",
            message_content or "(no content or missing message content intent)",
            "---",
        ]
        if attachments and not admin_files:
            admin_lines.append("Attachments:")
            admin_lines.extend(attachments)

        view = ReportReviewView(self.bot, self.config, self.db, report_id)
        admin_message = await admin_channel.send(
            content="\n".join(admin_lines),
            files=admin_files or None,
            view=view,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        await self.db.execute(
            "UPDATE reports SET admin_message_id = ? WHERE report_id = ?",
            (admin_message.id, report_id),
        )

        await interaction.followup.send(
            "Report submitted for admin review.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    config: Config = bot.config
    db: Database = bot.db
    await bot.add_cog(ReportsCog(bot, config, db))
