import sqlite3

DATABASE = "pump_sentinel.db"


def get_connection():
    return sqlite3.connect(DATABASE)


def init_database():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watched_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_address TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    connection.commit()
    connection.close()


def add_token(token_address):
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            "INSERT INTO watched_tokens (token_address) VALUES (?)",
            (token_address,)
        )
        connection.commit()
        result = True
    except sqlite3.IntegrityError:
        result = False

    connection.close()
    return result


def get_tokens():
    connection = get_connection()
    cursor = connection.cursor()

    cursor.execute(
        "SELECT token_address FROM watched_tokens"
    )

    tokens = [row[0] for row in cursor.fetchall()]

    connection.close()
    return tokens
