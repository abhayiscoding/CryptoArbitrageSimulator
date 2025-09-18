# Run this to check your database
import sqlite3
conn = sqlite3.connect('arbitrage.db')
cursor = conn.cursor()
cursor.execute("SELECT * FROM price_data LIMIT 5")
print(cursor.fetchall())
