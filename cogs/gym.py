import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
from typing import Annotated, Optional
from datetime import date, timedelta

# --- UI CLASSES ---
class HistoryDropdown(discord.ui.Select):
    def __init__(self, logs, db_name):
        self.db_name = db_name
        
        # Create an option for each log (Max 25)
        options = []
        for log in logs:
            # log = (id, activity, amount, xp, date)
            # Format: "20 Pushups (12-25)"
            date_short = log[4].split(" ")[0] # Get YYYY-MM-DD
            lbl = f"{log[2]} {log[1]} ({int(log[3])} XP)"
            desc = f"ID: {log[0]} | Date: {date_short}"
            
            options.append(discord.SelectOption(
                label=lbl, 
                description=desc, 
                value=str(log[0]), 
                emoji="🗑️"
            ))

        super().__init__(
            placeholder="Select a workout to DELETE it...", 
            min_values=1, 
            max_values=1, 
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        # 1. Identify the log
        log_id = int(self.values[0])
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # 2. Get details before deleting (to calculate refund)
        c.execute("SELECT user_id, guild_id, xp_earned, amount, activity_name FROM workout_logs WHERE id=?", (log_id,))
        row = c.fetchone()
        
        if not row:
            await interaction.response.send_message("❌ Log already deleted or not found.", ephemeral=True)
            conn.close()
            return
            
        user_id, guild_id, xp_remove, amount, activity = row
        
        # Security: Double check ownership
        if user_id != interaction.user.id:
            await interaction.response.send_message("⛔ You can only delete your own logs.", ephemeral=True)
            conn.close()
            return

        # 3. Revert User XP
        c.execute("UPDATE users SET xp_total = xp_total - ? WHERE discord_id = ? AND guild_id = ?", (xp_remove, user_id, guild_id))
        
        # 4. Revert Boss HP (Heal him back)
        # Find the latest boss for this guild (Active or most recently killed)
        c.execute("SELECT id, current_hp, max_hp FROM boss WHERE guild_id=? ORDER BY id DESC LIMIT 1", (guild_id,))
        boss_row = c.fetchone()
        if boss_row:
            b_id, current_hp, max_hp = boss_row
            # Heal boss, but don't go over Max HP
            new_hp = min(max_hp, current_hp + xp_remove)
            # If boss was dead (0 HP), revive him if he gets HP back
            is_active = 1 if new_hp > 0 else 0
            
            c.execute("UPDATE boss SET current_hp = ?, active = ? WHERE id=?", (new_hp, is_active, b_id))

        # 5. Delete the Log
        c.execute("DELETE FROM workout_logs WHERE id = ?", (log_id,))
        conn.commit()
        conn.close()

        # 6. User Feedback
        await interaction.response.send_message(
            f"🗑️ **Deleted:** {amount} {activity}. Removed {int(xp_remove)} damage from the boss.", 
            ephemeral=True
        )
        # Disable the selector so they can't click it again
        self.disabled = True
        await interaction.message.edit(view=self.view)

class HistoryView(discord.ui.View):
    def __init__(self, logs, db_name):
        super().__init__()
        self.add_item(HistoryDropdown(logs, db_name))


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
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server!", ephemeral=True)
            return


        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # 1. Check if boss is already alive
        c.execute("SELECT name, current_hp FROM boss WHERE guild_id=? AND active=1", (interaction.guild_id,))
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
        c.execute("INSERT INTO boss (guild_id, name, max_hp, current_hp, image_url, active) VALUES (?, ?, ?, ?, ?, 1)",
                  (interaction.guild_id, name, hp, hp, image_url))
        
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
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

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
        c.execute("INSERT OR IGNORE INTO users (discord_id, guild_id, username, xp_total) VALUES (?, ?, ?, 0)", 
                  (interaction.user.id, interaction.guild_id, interaction.user.name))
        c.execute("UPDATE users SET xp_total = xp_total + ? WHERE discord_id = ? AND guild_id = ?", (damage, interaction.user.id, interaction.guild_id))

        # 3. Update Group Streak (Logic: Is today > last_date?)
        today = date.today()
        
        # Ensure guild state exists
        c.execute("INSERT OR IGNORE INTO game_state (guild_id, group_streak, last_active_date) VALUES (?, 0, NULL)", (interaction.guild_id,))
        c.execute("SELECT group_streak, last_active_date FROM game_state WHERE guild_id=?", (interaction.guild_id,))
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
            c.execute("UPDATE game_state SET group_streak=?, last_active_date=? WHERE guild_id=?", (new_streak, today, interaction.guild_id))

        # 4. DAMAGE THE BOSS
        # Find the active boss for this guild
        c.execute("SELECT id, name, current_hp, max_hp, image_url, active FROM boss WHERE guild_id=? AND active=1", (interaction.guild_id,))
        boss_data = c.fetchone()
        
        boss_id = boss_data[0] if boss_data else None
        boss_name = boss_data[1] if boss_data else "Unknown"
        boss_hp = boss_data[2] if boss_data else 0
        boss_max = boss_data[3] if boss_data else 100
        boss_img = boss_data[4] if boss_data else None
        is_active = boss_data[5] if boss_data else 0

        boss_msg = ""
        if is_active and boss_hp > 0:
            new_hp = max(0, boss_hp - damage)
            c.execute("UPDATE boss SET current_hp = ? WHERE id=?", (new_hp, boss_id))
            
            # Health Bar Visual
            percent = int((new_hp / boss_max) * 10) # 0 to 10
            bar = "🟥" * percent + "⬜" * (10 - percent)
            
            boss_msg = f"**{boss_name} HP:** {bar} {int(new_hp)}/{int(boss_max)}"
            
            if new_hp == 0:
                boss_msg = f"💀 **VICTORY!** {interaction.user.display_name} landed the killing blow on **{boss_name}**!"
                c.execute("UPDATE boss SET active=0 WHERE id=?", (boss_id,))
        else:
            boss_msg = "💤 No active boss. Use `/boss_setup` to summon one!"

        conn.commit()
        conn.close()

        # 5. Response Embed
        embed = discord.Embed(title="⚔️ Attack Logged!", color=discord.Color.orange())
        embed.add_field(name="Attacker", value=interaction.user.display_name, inline=True)
        embed.add_field(name="Activity", value=f"{amount} {activity.name}", inline=True)
        embed.add_field(name="Damage Dealt", value=f"💥 {int(damage)}", inline=True)
        embed.add_field(name="Group Streak", value=f"🔥 {new_streak} Days", inline=True)
        
        embed.add_field(name="Boss Status", value=boss_msg, inline=False)
        
        if is_active and boss_img and boss_hp > 0:
            embed.set_thumbnail(url=boss_img)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="See who is dealing the most damage")
    async def leaderboard(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT discord_id, username, xp_total FROM users WHERE guild_id=? ORDER BY xp_total DESC LIMIT 5", (interaction.guild_id,))
        rows = c.fetchall()
        conn.close()

        msg = "**🏆 GYM LEADERBOARD 🏆**\n"
        for i, row in enumerate(rows):
            user_id, db_name, xp = row
            member = interaction.guild.get_member(user_id) if interaction.guild else None
            display_name = member.display_name if member else db_name
            msg += f"{i+1}. **{display_name}** - {xp} XP\n"

        await interaction.response.send_message(msg)

    # --- HISTORY COMMAND ---
    @app_commands.command(name="log_history", description="Manage your recent workouts")
    async def log_history(self, interaction: discord.Interaction):
        if not interaction.guild_id:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        
        # Fetch last 25 logs for user in this guild
        c.execute("""
            SELECT id, activity_name, amount, xp_earned, timestamp 
            FROM workout_logs 
            WHERE user_id = ? AND guild_id = ?
            ORDER BY id DESC LIMIT 25
        """, (interaction.user.id, interaction.guild_id))
        rows = c.fetchall()
        conn.close()

        if not rows:
            await interaction.response.send_message("📭 You haven't logged anything yet!", ephemeral=True)
            return

        embed = discord.Embed(title="📜 Recent History", description="Select a workout below to **permanently delete** it.", color=discord.Color.blue())
        
        view = HistoryView(rows, self.db_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Gym(bot))