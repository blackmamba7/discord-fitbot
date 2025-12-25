import sqlite3

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    # 1. Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        discord_id INTEGER PRIMARY KEY,
        username TEXT,
        xp_total REAL DEFAULT 0
    )''')

    # 2. Game State (Tracks the GROUP streak)
    c.execute('''CREATE TABLE IF NOT EXISTS game_state (
        id INTEGER PRIMARY KEY,
        group_streak INTEGER DEFAULT 0,
        last_active_date TEXT
    )''')
    # Initialize the row immediately
    c.execute("INSERT OR IGNORE INTO game_state (id, group_streak, last_active_date) VALUES (1, 0, NULL)")

    # 3. Boss (The current enemy)
    c.execute('''CREATE TABLE IF NOT EXISTS boss (
        id INTEGER PRIMARY KEY,
        name TEXT,
        max_hp REAL,
        current_hp REAL,
        image_url TEXT,
        active BOOLEAN DEFAULT 0
    )''')
    # Initialize the row immediately
    c.execute("INSERT OR IGNORE INTO boss (id, name, max_hp, current_hp, active) VALUES (1, 'Init', 0, 0, 0)")

    # 4. Activity Rules (XP System)
    c.execute('''CREATE TABLE IF NOT EXISTS activity_types (
        name TEXT PRIMARY KEY,
        xp_multiplier REAL
    )''')
    activities = [
        ('pushup', 1.0),    # 1 rep = 1 XP
        ('pullup', 5.0),    # 1 rep = 5 XP
        ('run', 10.0),      # 1 km = 10 XP
        ('squat', 1.5),     # 1 rep = 1.5 XP
        ('gym', 2.0),       # 1 min = 2 XP
        ('calories', 0.3),  # 1 calorie = 0.3 XP    
    ]
    c.executemany('INSERT OR IGNORE INTO activity_types VALUES (?, ?)', activities)

    # 5. Logs
    c.execute('''CREATE TABLE IF NOT EXISTS workout_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        activity_name TEXT,
        amount REAL,
        xp_earned REAL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(discord_id)
    )''')

    conn.commit()
    conn.close()
    print("✅ Database initialized successfully!")

if __name__ == '__main__':
    init_db()