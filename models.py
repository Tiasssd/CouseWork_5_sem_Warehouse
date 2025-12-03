# models.py - Функции работы с базой данных

import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from datetime import datetime, date
from decimal import Decimal
import json
import csv
from io import StringIO


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

        # Создаём запись в stock
        cursor.execute(
            "INSERT INTO stock (product_id, quantity) VALUES (%s, 0)", (product_id,)
        )

        conn.commit()
        return product_id
    finally:
        cursor.close()
        conn.close()


def decimal_default(obj):
    """Конвертер для Decimal, datetime и других типов в JSON"""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    # Пропускаем поля, которые не можем сериализовать
    return str(obj)


def update_product(
    product_id, sku, name, category, unit, min_stock, price, user_id=None
):
    """Обновить данные товара и записать историю изменения"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # 1) Получаем старые данные товара
        cursor.execute("SELECT * FROM products WHERE id = %s", (product_id,))
        old_row = cursor.fetchone()

        if not old_row:
            return

        # Оставляем только нужные поля
        old_data = {
            "sku": old_row["sku"],
            "name": old_row["name"],
            "category": old_row["category"],
            "unit": old_row["unit"],
            "min_stock": float(old_row["min_stock"]),
            "price": float(old_row["price"]),
        }

        # 2) Обновляем запись в products
        cursor.execute(
            """UPDATE products 
               SET sku=%s, name=%s, category=%s, unit=%s, min_stock=%s, price=%s 
               WHERE id=%s""",
            (sku, name, category, unit, min_stock, price, product_id),
        )

        # 3) Формируем новые данные товара
        new_data = {
            "sku": sku,
            "name": name,
            "category": category,
            "unit": unit,
            "min_stock": float(min_stock),
            "price": float(price),
        }

        # 4) Пишем в историю ЧЕРЕЗ ТОТ ЖЕ cursor
        if user_id is not None:
            log_product_change(
                cursor, product_id, "updated", old_data, new_data, user_id
            )

        # 5) Фиксируем транзакцию (обновление товара + история)
        conn.commit()
        print(f"Product {product_id} updated successfully")
    except Exception as e:
        conn.rollback()
        print(f"Error in update_product: {e}")
        raise
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


def search_products(query):
    """Поиск товаров по артикулу или названию"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        search_term = f"%{query}%"
        cursor.execute(
            """SELECT * FROM products 
               WHERE sku LIKE %s OR name LIKE %s OR category LIKE %s
               ORDER BY name""",
            (search_term, search_term, search_term),
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


# ============ ЭКСПОРТ ============


def export_movements_to_csv(date_from=None, date_to=None, product_id=None):
    """Получить движения для экспорта в CSV"""
    movements = get_movements(date_from, date_to, product_id)
    return movements


# ============ СТАТИСТИКА ============


def get_dashboard_stats():
    """Получить статистику для главной панели"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        stats = {}

        # Общее количество товаров
        cursor.execute("SELECT COUNT(*) as total FROM products")
        stats["total_products"] = cursor.fetchone()["total"]

        # Товары с низким остатком
        cursor.execute(
            """
            SELECT COUNT(*) as low_count FROM products p
            JOIN stock s ON p.id = s.product_id
            WHERE s.quantity < p.min_stock
        """
        )
        stats["low_stock_count"] = cursor.fetchone()["low_count"]

        # Операций за сегодня
        cursor.execute(
            """
            SELECT COUNT(*) as today_movements 
            FROM movements 
            WHERE DATE(movement_date) = CURDATE()
        """
        )
        stats["today_movements"] = cursor.fetchone()["today_movements"]

        # Общая стоимость товаров на складе
        cursor.execute(
            """
            SELECT COALESCE(SUM(s.quantity * p.price), 0) as total_value
            FROM stock s
            JOIN products p ON s.product_id = p.id
        """
        )
        stats["total_value"] = cursor.fetchone()["total_value"]

        return stats
    finally:
        cursor.close()
        conn.close()


# ============ ИСТОРИЯ ИЗМЕНЕНИЙ ============


def log_product_change(cursor, product_id, action, old_data, new_data, user_id):
    """Записать изменение товара в историю (использует переданный cursor)"""
    try:
        old_json = json.dumps(old_data, default=decimal_default, ensure_ascii=False)
        new_json = json.dumps(new_data, default=decimal_default, ensure_ascii=False)

        cursor.execute(
            """INSERT INTO product_history (product_id, action, old_data, new_data, changed_by)
               VALUES (%s, %s, %s, %s, %s)""",
            (product_id, action, old_json, new_json, user_id),
        )
        print(f"History record inserted for product {product_id}")
    except Exception as e:
        print(f"Error in log_product_change: {e}")
        raise


def get_product_history(product_id):
    """Получить историю изменений товара"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """SELECT h.*, u.login as user_login
               FROM product_history h
               LEFT JOIN users u ON h.changed_by = u.id
               WHERE h.product_id = %s
               ORDER BY h.changed_at DESC""",
            (product_id,),
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
