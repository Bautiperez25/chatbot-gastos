import sqlite3


def crear_base():
    conexion = sqlite3.connect("gastos.db")
    cursor = conexion.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS gastos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            monto REAL NOT NULL,
            categoria TEXT NOT NULL,
            medio_pago TEXT NOT NULL,
            personas INTEGER NOT NULL DEFAULT 1,
            fecha TEXT NOT NULL
        )
    """)

    conexion.commit()
    conexion.close()