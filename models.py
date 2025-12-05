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


def user_exists(login):
    """Проверить существует ли пользователь с таким логином"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE login = %s", (login,))
        result = cursor.fetchone()
        return result["count"] > 0
    finally:
        cursor.close()
        conn.close()


def get_all_users():
    """Получить всех пользователей"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, login, role, created_at FROM users ORDER BY id")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def delete_user_by_id(user_id):
    """Удалить пользователя"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
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


def get_stock_for_product(product_id):
    """Получить остаток конкретного товара"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT quantity FROM stock WHERE product_id = %s", (product_id,)
        )
        return cursor.fetchone()
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


# ============ ЗАКАЗЫ ПОСТАВЩИКАМ ============


def create_supplier_order(
    order_number, supplier_name, order_date, expected_date, notes, items, user_id
):
    """Создать заказ поставщику"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Создаём заказ
        cursor.execute(
            """
            INSERT INTO supplier_orders (order_number, supplier_name, order_date, expected_date, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """,
            (order_number, supplier_name, order_date, expected_date, notes, user_id),
        )

        order_id = cursor.lastrowid

        # Добавляем позиции заказа
        for item in items:
            cursor.execute(
                """
                INSERT INTO supplier_order_items (order_id, product_id, quantity, price)
                VALUES (%s, %s, %s, %s)
            """,
                (order_id, item["product_id"], item["quantity"], item.get("price", 0)),
            )

        conn.commit()
        return order_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def get_all_supplier_orders():
    """Получить все заказы поставщикам"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT so.*, u.login as created_by_name,
                   COUNT(soi.id) as items_count
            FROM supplier_orders so
            LEFT JOIN users u ON so.created_by = u.id
            LEFT JOIN supplier_order_items soi ON so.id = soi.order_id
            GROUP BY so.id
            ORDER BY so.order_date DESC
        """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def get_supplier_order_by_id(order_id):
    """Получить заказ поставщику с позициями"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM supplier_orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()

        if order:
            cursor.execute(
                """
                SELECT soi.*, p.sku, p.name, p.unit
                FROM supplier_order_items soi
                JOIN products p ON soi.product_id = p.id
                WHERE soi.order_id = %s
            """,
                (order_id,),
            )
            order["items"] = cursor.fetchall()  # ← ПРОВЕРЬ ЧТО ЕСТЬ ()

        return order
    finally:
        cursor.close()
        conn.close()


def get_supplier_order_by_id(order_id):
    """Получить заказ поставщику с позициями"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM supplier_orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()

        if order:
            cursor.execute(
                """
                SELECT soi.*, p.sku, p.name, p.unit
                FROM supplier_order_items soi
                JOIN products p ON soi.product_id = p.id
                WHERE soi.order_id = %s
            """,
                (order_id,),
            )
            order["order_items"] = cursor.fetchall()

        return order
    finally:
        cursor.close()
        conn.close()


def update_supplier_order_status(order_id, status, user_id):
    """Обновить статус заказа поставщику"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if status == "received":
            # Просто меняем статус, БЕЗ автоматического прихода
            # Приход делается через форму "Приход товара"
            cursor.execute(
                """
                UPDATE supplier_orders 
                SET status = %s, received_date = CURDATE()
                WHERE id = %s
            """,
                (status, order_id),
            )
        elif status == "cancelled":
            # Отмена заказа
            cursor.execute(
                """
                UPDATE supplier_orders SET status = %s WHERE id = %s
            """,
                (status, order_id),
            )
        else:
            cursor.execute(
                """
                UPDATE supplier_orders SET status = %s WHERE id = %s
            """,
                (status, order_id),
            )

        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_open_supplier_orders():
    """Получить открытые заказы поставщикам (новые и отправленные)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, order_number, supplier_name, status, order_date
            FROM supplier_orders
            WHERE status IN ('new', 'sent')
            ORDER BY order_date DESC
        """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


# ============ ЗАКАЗЫ ОТ КЛИЕНТОВ ============


def get_all_customer_orders():
    """Получить все заказы от клиентов"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT co.*, u.login as created_by_name,
                   COUNT(coi.id) as items_count
            FROM customer_orders co
            LEFT JOIN users u ON co.created_by = u.id
            LEFT JOIN customer_order_items coi ON co.id = coi.order_id
            GROUP BY co.id
            ORDER BY co.order_date DESC
        """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

def create_customer_order(order_number, customer_name, order_date, deadline_date, notes, items, user_id):
    """Создать заказ от клиента"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Создаём заказ
        cursor.execute("""
            INSERT INTO customer_orders (order_number, customer_name, order_date, deadline_date, notes, created_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (order_number, customer_name, order_date, deadline_date, notes, user_id))
        
        order_id = cursor.lastrowid
        
        # Добавляем позиции заказа
        for item in items:
            cursor.execute("""
                INSERT INTO customer_order_items (order_id, product_id, quantity)
                VALUES (%s, %s, %s)
            """, (order_id, item['product_id'], item['quantity']))
        
        conn.commit()
        return order_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def get_customer_order_by_id(order_id):
    """Получить заказ клиента с позициями"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM customer_orders WHERE id = %s", (order_id,))
        order = cursor.fetchone()

        if order:
            cursor.execute(
                """
                SELECT coi.*, p.sku, p.name, p.unit, s.quantity as stock_quantity
                FROM customer_order_items coi
                JOIN products p ON coi.product_id = p.id
                LEFT JOIN stock s ON p.id = s.product_id
                WHERE coi.order_id = %s
            """,
                (order_id,),
            )
            order["order_items"] = cursor.fetchall()  # ← ИЗМЕНЕНО

        return order
    finally:
        cursor.close()
        conn.close()


def update_customer_order_status(order_id, status, user_id):
    """Обновить статус заказа клиента"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if status == "shipped":
            # Автоматически делаем расход товаров
            order = get_customer_order_by_id(order_id)
            for item in order["order_items"]:
                remaining = item["quantity"] - item["shipped_quantity"]
                if remaining > 0:
                    # Проверяем есть ли достаточно товара
                    stock_info = get_stock_for_product(item["product_id"])
                    current_stock = float(stock_info["quantity"]) if stock_info else 0

                    if current_stock < remaining:
                        conn.rollback()
                        raise Exception(
                            f"Недостаточно товара '{item['name']}' на складе. Доступно: {current_stock}, требуется: {remaining}"
                        )

                    # Делаем расход
                    add_movement(
                        item["product_id"],
                        "outcome",
                        remaining,
                        f"Заказ клиента #{order['order_number']}",
                        user_id,
                    )

                    # Обновляем shipped_quantity
                    cursor.execute(
                        """
                        UPDATE customer_order_items 
                        SET shipped_quantity = shipped_quantity + %s
                        WHERE id = %s
                    """,
                        (remaining, item["id"]),
                    )

            cursor.execute(
                """
                UPDATE customer_orders 
                SET status = %s, shipped_date = CURDATE()
                WHERE id = %s
            """,
                (status, order_id),
            )
        elif status == "cancelled":
            # Отмена заказа
            cursor.execute(
                """
                UPDATE customer_orders SET status = %s WHERE id = %s
            """,
                (status, order_id),
            )
        else:
            cursor.execute(
                """
                UPDATE customer_orders SET status = %s WHERE id = %s
            """,
                (status, order_id),
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def update_supplier_order_item_received(order_id, product_id, quantity, user_id):
    """Обновить принятое количество товара в заказе поставщику
    и автоматически обновить статус заказа
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Обновляем received_quantity
        cursor.execute(
            """
            UPDATE supplier_order_items 
            SET received_quantity = received_quantity + %s
            WHERE order_id = %s AND product_id = %s
        """,
            (quantity, order_id, product_id),
        )

        # Проверяем выполнение всего заказа
        cursor.execute(
            """
            SELECT 
                SUM(quantity) as total_ordered,
                SUM(received_quantity) as total_received
            FROM supplier_order_items
            WHERE order_id = %s
        """,
            (order_id,),
        )

        result = cursor.fetchone()
        total_ordered = float(result["total_ordered"])
        total_received = float(result["total_received"])

        # Определяем новый статус
        if total_received == 0:
            new_status = "new"
        elif total_received >= total_ordered:
            new_status = "received"
        else:
            new_status = "in_progress"

        # Обновляем статус заказа
        if new_status == "received":
            cursor.execute(
                """
                UPDATE supplier_orders 
                SET status = %s, received_date = CURDATE()
                WHERE id = %s
            """,
                (new_status, order_id),
            )
        else:
            cursor.execute(
                """
                UPDATE supplier_orders 
                SET status = %s
                WHERE id = %s
            """,
                (new_status, order_id),
            )

        conn.commit()
    finally:
        cursor.close()
        conn.close()


def update_customer_order_item_shipped(order_id, product_id, quantity, user_id):
    """
    Обновить отгруженное количество товара в заказе клиента
    и автоматически обновить статус заказа
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Обновляем shipped_quantity
        cursor.execute(
            """
            UPDATE customer_order_items 
            SET shipped_quantity = shipped_quantity + %s
            WHERE order_id = %s AND product_id = %s
        """,
            (quantity, order_id, product_id),
        )

        # Проверяем выполнение всего заказа
        cursor.execute(
            """
            SELECT 
                SUM(quantity) as total_ordered,
                SUM(shipped_quantity) as total_shipped
            FROM customer_order_items
            WHERE order_id = %s
        """,
            (order_id,),
        )

        result = cursor.fetchone()
        total_ordered = float(result["total_ordered"])
        total_shipped = float(result["total_shipped"])

        # Определяем новый статус
        if total_shipped == 0:
            new_status = "new"
        elif total_shipped >= total_ordered:
            new_status = "shipped"
        else:
            new_status = "in_progress"

        # Обновляем статус заказа
        if new_status == "shipped":
            cursor.execute(
                """
                UPDATE customer_orders 
                SET status = %s, shipped_date = CURDATE()
                WHERE id = %s
            """,
                (new_status, order_id),
            )
        else:
            cursor.execute(
                """
                UPDATE customer_orders 
                SET status = %s
                WHERE id = %s
            """,
                (new_status, order_id),
            )

        conn.commit()
    finally:
        cursor.close()
        conn.close()


def get_open_customer_orders():
    """Получить открытые заказы клиентов для выбора в форме расхода"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, order_number, customer_name, status, order_date
            FROM customer_orders
            WHERE status IN ('new', 'in_progress', 'ready')
            ORDER BY order_date DESC
        """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


def update_customer_order_status(order_id, status, user_id):
    """Обновить статус заказа клиента"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        if status == "shipped":
            # Автоматически делаем расход товаров
            order = get_customer_order_by_id(order_id)
            for item in order["order_items"]:  # ← ЗДЕСЬ order_items
                remaining = item["quantity"] - item["shipped_quantity"]
                if remaining > 0:
                    # Проверяем есть ли достаточно товара
                    stock_info = get_stock_for_product(item["product_id"])
                    current_stock = float(stock_info["quantity"]) if stock_info else 0

                    if current_stock < remaining:
                        conn.rollback()
                        raise Exception(
                            f"Недостаточно товара '{item['name']}' на складе. Доступно: {current_stock}, требуется: {remaining}"
                        )

                    # Делаем расход
                    add_movement(
                        item["product_id"],
                        "outcome",
                        remaining,
                        f"Заказ клиента #{order['order_number']}",
                        user_id,
                    )

                    # Обновляем shipped_quantity
                    cursor.execute(
                        """
                        UPDATE customer_order_items 
                        SET shipped_quantity = shipped_quantity + %s
                        WHERE id = %s
                    """,
                        (remaining, item["id"]),
                    )

            cursor.execute(
                """
                UPDATE customer_orders 
                SET status = %s, shipped_date = CURDATE()
                WHERE id = %s
            """,
                (status, order_id),
            )
        else:
            cursor.execute(
                """
                UPDATE customer_orders SET status = %s WHERE id = %s
            """,
                (status, order_id),
            )

        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()


def get_open_customer_orders():
    """Получить открытые заказы клиентов для выбора в форме расхода"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, order_number, customer_name, status
            FROM customer_orders
            WHERE status IN ('new', 'in_progress', 'ready')
            ORDER BY order_date DESC
        """
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()
