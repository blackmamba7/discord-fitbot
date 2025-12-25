import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from typing import Annotated, Optional
from datetime import date, timedelta

# Simple static list for autocomplete; you can replace with DB-backed list.
ACTIVITIES = ["pushup", "pullup", "run", "squat", "gym"]

# async def activity_autocomplete(interaction: discord.Interaction, current: str):
#     return [
#         app_commands.Choice(name=a, value=a)
#         for a in ACTIVITIES
#         if current.lower() in a.lower()
#     ][:25]

class Gym(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_name = 'database.db'

    def get_xp_multiplier(self, activity_name):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT xp_multiplier FROM activity_types WHERE name = ?", (activity_name,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None

    # --- BOSS SETUP COMMAND ---
    @app_commands.command(name="boss_setup", description="Summon a new boss for the group to fight!")
    @app_commands.describe(name="Boss Name", hp="Total Health Points", image="Boss Image")
    async def boss_setup(self, interaction: discord.Interaction, name: str, hp: float, image: Optional[discord.Attachment] = None):
        
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # 1. Check if boss is already alive
        c.execute("SELECT name, current_hp FROM boss WHERE id=1 AND active=1")
        existing_boss = c.fetchone()
        
        if existing_boss and existing_boss[1] > 0:
            await interaction.response.send_message(
                f"⚠️ **Cannot summon!** '{existing_boss[0]}' is still alive with {existing_boss[1]} HP. Finish the fight first!", 
                ephemeral=True
            )
            conn.close()
            return

        # 2. Create New Boss
        image_url = image.url if image else None
        c.execute("""
            UPDATE boss 
            SET name=?, max_hp=?, current_hp=?, image_url=?, active=1 
            WHERE id=1
        """, (name, hp, hp, image_url))
        
        conn.commit()
        conn.close()
        
        # 3. Announce
        embed = discord.Embed(title=f"👹 A NEW CHALLENGER APPEARS!", description=f"**{name}** has arrived!", color=discord.Color.red())
        embed.add_field(name="❤️ HP", value=f"{hp}/{hp}", inline=True)
        if image_url:
            embed.set_thumbnail(url=image_url)
            
        await interaction.response.send_message(embed=embed)

    # --- LOG COMMAND (UPDATED) ---
    @app_commands.command(name="log", description="Log a workout and attack the boss!")
    @app_commands.choices(activity=[
        app_commands.Choice(name="Pushups (Reps)", value="pushup"),
        app_commands.Choice(name="Pullups (Reps)", value="pullup"),
        app_commands.Choice(name="Running (KM)", value="run"),
        app_commands.Choice(name="Squats (Reps)", value="squat"),
        app_commands.Choice(name="Gym Session (Mins)", value="gym"),
        app_commands.Choice(name="Calories Burned (kcal)", value="calories"),
    ])
    async def log_workout(self, interaction: discord.Interaction, activity: app_commands.Choice[str], amount: float):
        
        # 1. Calculate Damage (XP)
        activity_name = activity.value
        multiplier = self.get_xp_multiplier(activity_name)
        if multiplier is None:
            await interaction.response.send_message(f"⚠️ Error: XP Multiplier for '{activity_name}' not found in DB.", ephemeral=True)
            return
            
        damage = amount * multiplier

        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()

        # 2. Update User Stats (Total Damage Dealt)
        c.execute("INSERT OR IGNORE INTO users (discord_id, username, xp_total) VALUES (?, ?, 0)", 
                  (interaction.user.id, interaction.user.name))
        c.execute("UPDATE users SET xp_total = xp_total + ? WHERE discord_id = ?", (damage, interaction.user.id))

        # 3. Update Group Streak (Logic: Is today > last_date?)
        # group_streak table has only one row with id=1
        today = date.today()
        
        c.execute("SELECT group_streak, last_active_date FROM game_state WHERE id=1")
        row = c.fetchone()
        current_streak = row[0]
        last_date = date.fromisoformat(row[1]) if row[1] else None

        new_streak = current_streak
        if last_date != today:
            # First workout of the day!
            if last_date == today - timedelta(days=1):
                new_streak += 1 # Kept the streak
            else:
                new_streak = 1 # Reset or Start new
            
            # Save new date/streak
            c.execute("UPDATE game_state SET group_streak=?, last_active_date=? WHERE id=1", (new_streak, today))

        # 4. DAMAGE THE BOSS
        # boss table has only one row with id=1
        c.execute("SELECT name, current_hp, max_hp, image_url, active FROM boss WHERE id=1")
        boss_data = c.fetchone()
        
        boss_name = boss_data[0] if boss_data else "Unknown"
        boss_hp = boss_data[1] if boss_data else 0
        boss_max = boss_data[2] if boss_data else 100
        boss_img = boss_data[3] if boss_data else None
        is_active = boss_data[4] if boss_data else 0

        boss_msg = ""
        if is_active and boss_hp > 0:
            new_hp = max(0, boss_hp - damage)
            c.execute("UPDATE boss SET current_hp = ? WHERE id=1", (new_hp,))
            
            # Health Bar Visual
            percent = int((new_hp / boss_max) * 10) # 0 to 10
            bar = "🟥" * percent + "⬜" * (10 - percent)
            
            boss_msg = f"**{boss_name} HP:** {bar} {int(new_hp)}/{int(boss_max)}"
            
            if new_hp == 0:
                boss_msg = f"💀 **VICTORY!** {interaction.user.name} landed the killing blow on **{boss_name}**!"
                c.execute("UPDATE boss SET active=0 WHERE id=1")
        else:
            boss_msg = "💤 No active boss. Use `/boss_setup` to summon one!"

        conn.commit()
        conn.close()

        # 5. Response Embed
        embed = discord.Embed(title="⚔️ Attack Logged!", color=discord.Color.orange())
        embed.add_field(name="Attacker", value=interaction.user.name, inline=True)
        embed.add_field(name="Activity", value=f"{amount} {activity.name}", inline=True)
        embed.add_field(name="Damage Dealt", value=f"💥 {int(damage)}", inline=True)
        embed.add_field(name="Group Streak", value=f"🔥 {new_streak} Days", inline=True)
        
        embed.add_field(name="Boss Status", value=boss_msg, inline=False)
        
        if is_active and boss_img and boss_hp > 0:
            embed.set_thumbnail(url=boss_img)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="See who is dealing the most damage")
    async def leaderboard(self, interaction: discord.Interaction):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT username, xp_total FROM users ORDER BY xp_total DESC LIMIT 5")
        rows = c.fetchall()
        conn.close()

        msg = "**🏆 GYM LEADERBOARD 🏆**\n"
        for i, row in enumerate(rows):
            msg += f"{i+1}. **{row[0]}** - {row[1]} XP\n"

        await interaction.response.send_message(msg)

async def setup(bot):
    await bot.add_cog(Gym(bot))