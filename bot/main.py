import logging
import sys

import discord
from discord.ext import commands

from bot.config import Config
from bot.db import Database
logger = logging.getLogger(__name__)

class BanHammerBot(commands.Bot):
    def __init__(self, config: Config, db: Database) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.db = db

    async def setup_hook(self) -> None:
        await self.db.init()
        if self.config.email_verification_enabled:
            await self.load_extension("bot.cogs.verification")
        await self.load_extension("bot.cogs.reports")
        guild = discord.Object(id=self.config.guild_id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync()

    async def on_ready(self) -> None:
        logger.info("Bot is ready as %s", self.user)
        channel = self.get_channel(self.config.admin_channel_id)
        logger.info("Admin channel: %s", channel)
        if channel:
            await channel.send("Discord Bot is online and ready.")
        else:
            logger.warning("Admin channel not found: %s", self.config.admin_channel_id)


def _configure_logging(level: str) -> None:
    discord.utils.setup_logging(level=level, root=True)


def main() -> None:
    config = Config.from_env()
    _configure_logging(config.log_level)
    db = Database(config.db_path)
    bot = BanHammerBot(config, db)
    bot.run(config.discord_token)


if __name__ == "__main__":
    main()
