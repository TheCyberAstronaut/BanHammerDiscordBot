import hashlib
import logging
import re
import secrets
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from bot.config import Config
from bot.db import Database
from bot.email_service import EmailService


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot, config: Config, db: Database) -> None:
        self.bot = bot
        self.config = config
        self.db = db
        self.email_service = EmailService(
            host=config.smtp_host,
            port=config.smtp_port,
            user=config.smtp_user,
            password=config.smtp_password,
            use_tls=config.smtp_use_tls,
            email_from=config.email_from,
        )

    def _is_domain_allowed(self, email: str) -> bool:
        domain = email.split("@")[-1].lower()
        logger.debug(
            "Checking domain allowlist/denylist: domain=%s allowlist=%s denylist=%s",
            domain,
            sorted(self.config.verification_domain_allowlist),
            sorted(self.config.verification_domain_denylist),
        )
        if self.config.verification_domain_allowlist and (
            domain not in self.config.verification_domain_allowlist
        ):
            logger.info("Domain blocked by allowlist: %s", domain)
            return False
        if self.config.verification_domain_denylist and (
            domain in self.config.verification_domain_denylist
        ):
            logger.info("Domain blocked by denylist: %s", domain)
            return False
        logger.debug("Domain allowed: %s", domain)
        return True

    async def _get_user_record(self, user_id: int) -> Optional[dict]:
        return await self.db.fetchone(
            "SELECT * FROM users_verification WHERE user_id = ?",
            (user_id,),
        )

    def _is_verified(self, member: discord.Member) -> bool:
        return any(role.id == self.config.verified_role_id for role in member.roles)

    @app_commands.command(name="verify_start", description="Start email verification")
    async def verify_start(self, interaction: discord.Interaction, email: str) -> None:
        if not self.config.email_verification_enabled:
            await interaction.response.send_message(
                "Email verification is disabled.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not _EMAIL_RE.match(email):
            logger.info("Invalid email format user_id=%s", interaction.user.id)
            await interaction.followup.send("Invalid email format.", ephemeral=True)
            return
        if not self._is_domain_allowed(email):
            logger.info(
                "Email domain rejected user_id=%s email=%s",
                interaction.user.id,
                email,
            )
            await interaction.followup.send(
                "Email domain is not allowed for verification.", ephemeral=True
            )
            return

        now = int(time.time())
        token = secrets.token_urlsafe(8)
        token_hash = _hash_token(token)
        expiry = now + self.config.verification_token_ttl_minutes * 60

        existing = await self._get_user_record(interaction.user.id)
        if isinstance(interaction.user, discord.Member) and self._is_verified(
            interaction.user
        ):
            logger.info("User already verified user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "You are already verified.", ephemeral=True
            )
            return

        if existing:
            logger.debug("Updating verification record user_id=%s", interaction.user.id)
            await self.db.execute(
                """
                UPDATE users_verification
                SET email = ?, status = ?, token_hash = ?, token_expiry = ?
                WHERE user_id = ?
                """,
                (email, "pending", token_hash, expiry, interaction.user.id),
            )
        else:
            logger.debug("Creating verification record user_id=%s", interaction.user.id)
            await self.db.execute(
                """
                INSERT INTO users_verification
                (user_id, email, status, token_hash, token_expiry, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (interaction.user.id, email, "pending", token_hash, expiry, now),
            )

        try:
            logger.debug("Sending verification email user_id=%s email=%s smtp_host=%s smtp_port=%s",
                         interaction.user.id, email, self.config.smtp_host, self.config.smtp_port
                        )
            self.email_service.send_verification_email(email, token)
        except Exception:
            logger.exception(
                "Failed to send verification email user_id=%s",
                interaction.user.id,
            )
            await interaction.followup.send(
                "Failed to send verification email. Please try again later.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Verification email sent. Use /verify_confirm with the code.",
            ephemeral=True,
        )

    @app_commands.command(name="verify_confirm", description="Confirm email verification")
    async def verify_confirm(self, interaction: discord.Interaction, code: str) -> None:
        if not self.config.email_verification_enabled:
            await interaction.response.send_message(
                "Email verification is disabled.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        record = await self._get_user_record(interaction.user.id)
        if not record:
            logger.info("No verification record user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "No verification request found. Use /verify_start first.",
                ephemeral=True,
            )
            return

        if isinstance(interaction.user, discord.Member) and self._is_verified(
            interaction.user
        ):
            logger.info("User already verified user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "You are already verified.", ephemeral=True
            )
            return

        now = int(time.time())
        if record.get("token_expiry") and now > int(record["token_expiry"]):
            logger.info("Verification token expired user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "Verification code expired. Use /verify_start to resend.",
                ephemeral=True,
            )
            return

        if _hash_token(code) != record.get("token_hash"):
            logger.info("Invalid verification code user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "Invalid verification code.", ephemeral=True
            )
            return

        await self.db.execute(
            """
            UPDATE users_verification
            SET status = ?, verified_at = ?
            WHERE user_id = ?
            """,
            ("verified", now, interaction.user.id),
        )

        role = interaction.guild.get_role(self.config.verified_role_id)
        if role and isinstance(interaction.user, discord.Member):
            await interaction.user.add_roles(role, reason="Email verified")
            logger.info("Assigned verified role user_id=%s", interaction.user.id)
        else:
            logger.warning(
                "Verified role not found or invalid member user_id=%s",
                interaction.user.id,
            )

        await self.db.execute(
            "DELETE FROM users_verification WHERE user_id = ?",
            (interaction.user.id,),
        )
        logger.debug("Verification record removed user_id=%s", interaction.user.id)

        await interaction.followup.send("Verification complete.", ephemeral=True)

    @app_commands.command(name="verify_status", description="Check verification status")
    async def verify_status(self, interaction: discord.Interaction) -> None:
        if not self.config.email_verification_enabled:
            await interaction.response.send_message(
                "Email verification is disabled.", ephemeral=True
            )
            return
        if isinstance(interaction.user, discord.Member) and self._is_verified(
            interaction.user
        ):
            await interaction.response.send_message(
                "Verification status: verified", ephemeral=True
            )
            return

        record = await self._get_user_record(interaction.user.id)
        if not record:
            logger.info("No verification record user_id=%s", interaction.user.id)
            await interaction.response.send_message(
                "You have not started verification.", ephemeral=True
            )
            return
        status = record.get("status", "pending")
        await interaction.response.send_message(
            f"Verification status: {status}", ephemeral=True
        )

    @app_commands.command(name="verify_resend", description="Resend verification email")
    async def verify_resend(self, interaction: discord.Interaction) -> None:
        if not self.config.email_verification_enabled:
            await interaction.response.send_message(
                "Email verification is disabled.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        record = await self._get_user_record(interaction.user.id)
        if not record:
            logger.info("No verification record user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "No verification request found. Use /verify_start first.",
                ephemeral=True,
            )
            return

        if isinstance(interaction.user, discord.Member) and self._is_verified(
            interaction.user
        ):
            logger.info("User already verified user_id=%s", interaction.user.id)
            await interaction.followup.send(
                "You are already verified.", ephemeral=True
            )
            return

        email = record.get("email")
        if not email:
            await interaction.followup.send(
                "No email on record. Use /verify_start again.",
                ephemeral=True,
            )
            return

        now = int(time.time())
        token = secrets.token_urlsafe(8)
        token_hash = _hash_token(token)
        expiry = now + self.config.verification_token_ttl_minutes * 60

        await self.db.execute(
            """
            UPDATE users_verification
            SET token_hash = ?, token_expiry = ?
            WHERE user_id = ?
            """,
            (token_hash, expiry, interaction.user.id),
        )
        logger.debug("Resent verification token user_id=%s", interaction.user.id)

        try:
            logger.debug("Resend verification email user_id=%s", interaction.user.id)
            self.email_service.send_verification_email(email, token)
        except Exception:
            logger.exception(
                "Failed to resend verification email user_id=%s",
                interaction.user.id,
            )
            await interaction.followup.send(
                "Failed to send verification email. Please try again later.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            "Verification email resent.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    config: Config = bot.config
    db: Database = bot.db
    await bot.add_cog(VerificationCog(bot, config, db))
