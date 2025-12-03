# models.py - Функции работы с базой данных

import pymysql
from decimal import Decimal
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from datetime import datetime


def get_db_connection():
    """Создаёт подключение к MySQL"""
    connection = pymysql.connect(
        host=Config.MYSQL_HOST,
        user=Config.MYSQL_USER,
        password=Config.MYSQL_PASSWORD,
        database=Config.MYSQL_DB,
        charset=Config.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
    )
    return connection


# ============ ПОЛЬЗОВАТЕЛИ ============


def authenticate_user(login, password):
    """Проверка логина и пароля. Возвращает данные пользователя или None"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM users WHERE login = %s", (login,))
        user = cursor.fetchone()
        if user and check_password_hash(user["password_hash"], password):
            return user
        return None
    finally:
        cursor.close()
        conn.close()


def create_user(login, password, role="warehouse"):
    """Создание нового пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        password_hash = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO users (login, password_hash, role) VALUES (%s, %s, %s)",
            (login, password_hash, role),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        cursor.close()
        conn.close()


# ============ ТОВАРЫ ============


def get_all_products():
    """Получить список всех товаров"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM products ORDER BY name")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_product_by_id(product_id):
    """Получить товар по ID"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        return cursor.fetchone()
    finally:
        cursor.close()
        conn.close()


def add_product(sku, name, category, unit, min_stock, price):
    """Добавить новый товар"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO products (sku, name, category, unit, min_stock, price) 
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (sku, name, category, unit, min_stock, price),
        )
        product_id = cursor.lastrowid
        # Создаём запись в stock с нулевым остатком
        cursor.execute(
            "INSERT INTO stock (product_id, quantity) VALUES (%s, 0)", (product_id,)
        )
        conn.commit()
        return product_id
    finally:
        cursor.close()
        conn.close()


def update_product(product_id, sku, name, category, unit, min_stock, price):
    """Обновить данные товара"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """UPDATE products 
               SET sku=%s, name=%s, category=%s, unit=%s, min_stock=%s, price=%s 
               WHERE id=%s""",
            (sku, name, category, unit, min_stock, price, product_id),
        )
        conn.commit()
    finally:
        cursor.close()
        conn.close()


def delete_product(product_id):
    """Удалить товар (каскадно удалятся stock и movements)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM products WHERE id = %s", (product_id,))
        conn.commit()
    finally:
        cursor.close()
        conn.close()


# ============ ОСТАТКИ ============


def get_stock():
    """Получить остатки с данными товаров"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT p.*, s.quantity 
               FROM products p
               LEFT JOIN stock s ON p.id = s.product_id
               ORDER BY p.name"""
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_low_stock_products():
    """Товары с остатком ниже минимального"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT p.*, s.quantity 
               FROM products p
               LEFT JOIN stock s ON p.id = s.product_id
               WHERE s.quantity < p.min_stock
               ORDER BY s.quantity ASC"""
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# ============ ДВИЖЕНИЯ ============


def add_movement(product_id, movement_type, quantity, comment, user_id):
    """
    Добавить операцию прихода/расхода.
    movement_type: 'income' или 'outcome'
    Возвращает: (success: bool, message: str)
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Преобразуем в Decimal для совместимости с MySQL
        quantity = Decimal(str(quantity))

        # Получаем текущий остаток
        cursor.execute(
            "SELECT quantity FROM stock WHERE product_id = %s", (product_id,)
        )
        stock_row = cursor.fetchone()
        current_qty = Decimal(str(stock_row["quantity"])) if stock_row else Decimal("0")

        # Проверка для расхода
        if movement_type == "outcome":
            if current_qty < quantity:
                return (
                    False,
                    f"Недостаточно товара на складе. Доступно: {current_qty}",
                )

        # Записываем движение
        cursor.execute(
            """INSERT INTO movements (product_id, type, quantity, comment, user_id) 
               VALUES (%s, %s, %s, %s, %s)""",
            (product_id, movement_type, float(quantity), comment, user_id),
        )

        # Обновляем остаток
        if movement_type == "income":
            new_qty = current_qty + quantity
        else:  # outcome
            new_qty = current_qty - quantity

        cursor.execute(
            "UPDATE stock SET quantity = %s WHERE product_id = %s",
            (float(new_qty), product_id),
        )

        conn.commit()
        return (True, "Операция успешно выполнена")
    except Exception as e:
        conn.rollback()
        return (False, f"Ошибка: {str(e)}")
    finally:
        cursor.close()
        conn.close()


def get_movements(date_from=None, date_to=None, product_id=None):
    """Получить журнал движений с фильтрами"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        query = """
            SELECT m.*, p.name as product_name, p.sku, u.login as user_login
            FROM movements m
            JOIN products p ON m.product_id = p.id
            LEFT JOIN users u ON m.user_id = u.id
            WHERE 1=1
        """
        params = []

        if date_from:
            query += " AND m.movement_date >= %s"
            params.append(date_from)
        if date_to:
            query += " AND m.movement_date <= %s"
            params.append(date_to)
        if product_id:
            query += " AND m.product_id = %s"
            params.append(product_id)

        query += " ORDER BY m.movement_date DESC"

        cursor.execute(query, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
