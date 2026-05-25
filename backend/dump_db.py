import sqlite3

def dump_db():
    conn = sqlite3.connect('arctic_logistics.db')
    cursor = conn.cursor()
    
    # Get all table names
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith('sqlite_')]
    
    for table in tables:
        print(f"\n--- Table: {table} ---")
        cursor.execute(f"SELECT * FROM {table}")
        colnames = [description[0] for description in cursor.description]
        print(" | ".join(colnames))
        print("-" * (len(" | ".join(colnames))))
        rows = cursor.fetchall()
        for row in rows:
            print(" | ".join(str(item) for item in row))
    
    conn.close()

if __name__ == "__main__":
    dump_db()
