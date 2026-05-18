import sqlite3
conn = sqlite3.connect('data/articles.db')
cursor = conn.cursor()
cursor.execute('''
    SELECT id, judul, url, processing_error, fetch_attempts
    FROM articles
    WHERE content_fetched = -1
    ORDER BY id
''')
rows = cursor.fetchall()
print(f'Total failed: {len(rows)}')
print()
for row in rows:
    print(f'ID: {row[0]}')
    print(f'Judul: {row[1][:70]}')
    print(f'URL: {row[2][:80]}')
    print(f'Error: {row[3]}')
    print(f'Attempts: {row[4]}')
    print('-' * 60)
conn.close()
