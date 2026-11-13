import discord


async def try_delete_message(message: discord.Message) -> bool:
    try:
        await message.delete()
        return True
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        return False
