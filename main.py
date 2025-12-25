import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

# Intents (Must match what you enabled in Developer Portal)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def on_ready():
    print(f'🤖 Logged in as {bot.user} (ID: {bot.user.id})')
    print('------')
    if not getattr(bot, "commands_synced", False):
        await bot.tree.sync()
        bot.commands_synced = True
        print("🔁 Synced")

async def load_extensions():
    # Looks for files in the 'cogs' folder
    if os.path.exists('./cogs'):
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f'⚙️ Loaded extension: {filename}')
    else:
        print("⚠️ 'cogs' directory not found.")

async def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ Error: DISCORD_TOKEN not found in environment variables.")
        return

    async with bot:
        await load_extensions()
        await bot.start(token)

# This command forces an update immediately to YOUR server only.
@bot.command()
@commands.is_owner()
async def sync(ctx):
    print("Started sync...")
    # 1. Copy global commands to this specific server
    bot.tree.copy_global_to(guild=ctx.guild)
    # 2. Sync to this specific server (Instant)
    await bot.tree.sync(guild=ctx.guild)
    await ctx.send(f"✅ **Synced!** I updated the slash commands for **{ctx.guild.name}**. You should see them instantly.")

if __name__ == '__main__':
    asyncio.run(main())