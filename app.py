# app.py - Главный файл Flask приложения

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    make_response,
)
from decimal import Decimal
from functools import wraps
from config import Config
from io import StringIO
from datetime import datetime
import models
import csv


app = Flask(__name__)
app.config.from_object(Config)

# ============ ДЕКОРАТОРЫ ============


def login_required(f):
    """Декоратор для защиты роутов, требующих авторизации"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Пожалуйста, войдите в систему", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """Декоратор для защиты роутов, требующих прав администратора"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Пожалуйста, войдите в систему", "warning")
            return redirect(url_for("login"))
        if session.get("user_role") != "admin":
            flash("Доступ запрещён. Требуются права администратора", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


# ============ АВТОРИЗАЦИЯ ============


@app.route("/")
def index():
    """Главная страница - редирект на dashboard или login"""
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Страница входа"""
    if request.method == "POST":
        login = request.form.get("login")
        password = request.form.get("password")

        user = models.authenticate_user(login, password)
        if user:
            session["user_id"] = user["id"]
            session["user_login"] = user["login"]
            session["user_role"] = user["role"]
            flash(f'Добро пожаловать, {user["login"]}!', "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Неверный логин или пароль", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Регистрация нового пользователя"""
    if request.method == "POST":
        login = request.form.get("login", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")
        role = request.form.get("role", "warehouse")

        # Валидация
        if len(login) < 3:
            flash("Логин должен быть не менее 3 символов", "danger")
            return render_template("register.html")

        if len(password) < 6:
            flash("Пароль должен быть не менее 6 символов", "danger")
            return render_template("register.html")

        if password != password_confirm:
            flash("Пароли не совпадают", "danger")
            return render_template("register.html")

        # Проверка существования пользователя
        if models.user_exists(login):
            flash("Пользователь с таким логином уже существует", "danger")
            return render_template("register.html")

        # Создаём пользователя
        try:
            models.create_user(login, password, role)
            flash("Регистрация успешна! Теперь войдите в систему", "success")
            return redirect(url_for("login"))
        except Exception as e:
            flash(f"Ошибка при регистрации: {str(e)}", "danger")

    return render_template("register.html")


@app.route("/logout")
def logout():
    """Выход из системы"""
    session.clear()
    flash("Вы вышли из системы", "info")
    return redirect(url_for("login"))


# ============ ГЛАВНАЯ ПАНЕЛЬ ============


@app.route("/dashboard")
@login_required
def dashboard():
    """Главная панель с статистикой"""
    stats = models.get_dashboard_stats()
    return render_template("dashboard.html", stats=stats)


@app.route("/users")
@login_required
@admin_required
def users():
    """Список пользователей (только для админа)"""
    if session.get("user_role") != "admin":
        flash("Доступ запрещён", "danger")
        return redirect(url_for("dashboard"))

    all_users = models.get_all_users()
    return render_template("users.html", users=all_users)


@app.route("/users/delete/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def delete_user(user_id):
    """Удалить пользователя (только админ)"""
    if session.get("user_role") != "admin":
        flash("Доступ запрещён", "danger")
        return redirect(url_for("dashboard"))

    # Нельзя удалить самого себя
    if user_id == session["user_id"]:
        flash("Нельзя удалить свой аккаунт", "danger")
        return redirect(url_for("users"))

    try:
        models.delete_user_by_id(user_id)
        flash("Пользователь удалён", "success")
    except Exception as e:
        flash(f"Ошибка: {str(e)}", "danger")

    return redirect(url_for("users"))


# ============ ТОВАРЫ ============


@app.route("/products")
@login_required
def products():
    """Список товаров с поиском"""
    search_query = request.args.get("search", "").strip()

    if search_query:
        products = models.search_products(search_query)
    else:
        products = models.get_all_products()

    return render_template(
        "products.html", products=products, search_query=search_query
    )


@app.route("/api/product/<int:product_id>")
@login_required
def get_product_info(product_id):
    """API для получения информации о товаре"""
    from flask import jsonify

    product = models.get_product_by_id(product_id)
    if not product:
        return jsonify({"error": "Товар не найден"}), 404

    # Получаем текущий остаток
    stock_info = models.get_stock_for_product(product_id)

    return jsonify(
        {
            "id": product["id"],
            "sku": product["sku"],
            "name": product["name"],
            "category": product["category"] or "-",
            "unit": product["unit"],
            "min_stock": float(product["min_stock"]),
            "price": float(product["price"]),
            "current_stock": float(stock_info["quantity"]) if stock_info else 0,
        }
    )


@app.route("/api/supplier_order/<int:order_id>/items")
@login_required
def get_supplier_order_items(order_id):
    """API для получения товаров из заказа поставщику"""
    from flask import jsonify

    order = models.get_supplier_order_by_id(order_id)
    if not order:
        return jsonify({"error": "Заказ не найден"}), 404

    items = []
    for item in order["order_items"]:
        items.append(
            {
                "id": item["id"],
                "product_id": item["product_id"],
                "sku": item["sku"],
                "name": item["name"],
                "unit": item["unit"],
                "quantity": float(item["quantity"]),
                "price": float(item["price"]),
            }
        )

    return jsonify(
        {
            "order_number": order["order_number"],
            "supplier_name": order["supplier_name"],
            "items": items,
        }
    )


@app.route("/products/add", methods=["POST"])
@login_required
@admin_required
def add_product():
    """Добавить новый товар"""
    try:
        sku = request.form.get("sku")
        name = request.form.get("name")
        category = request.form.get("category", "")
        unit = request.form.get("unit", "шт")
        min_stock = float(request.form.get("min_stock", 0))
        price = float(request.form.get("price", 0))

        models.add_product(sku, name, category, unit, min_stock, price)
        flash("Товар успешно добавлен", "success")
    except Exception as e:
        flash(f"Ошибка при добавлении товара: {str(e)}", "danger")

    return redirect(url_for("products"))


@app.route("/products/edit/<int:product_id>", methods=["GET", "POST"])
@login_required
@admin_required
def edit_product(product_id):
    """Редактировать товар"""
    if request.method == "POST":
        try:
            sku = request.form.get("sku")
            name = request.form.get("name")
            category = request.form.get("category", "")
            unit = request.form.get("unit", "шт")
            min_stock = float(request.form.get("min_stock", 0))
            price = float(request.form.get("price", 0))

            # DEBUG: выводим что получили
            print(f"DEBUG: Updating product {product_id}")
            print(f"  SKU: {sku}, Name: {name}, Category: {category}")
            print(f"  Unit: {unit}, Min: {min_stock}, Price: {price}")
            print(f"  User ID: {session['user_id']}")

            models.update_product(
                product_id,
                sku,
                name,
                category,
                unit,
                min_stock,
                price,
                session["user_id"],
            )

            flash("Товар успешно обновлён", "success")
            return redirect(url_for("products"))
        except Exception as e:
            # Выводим полную ошибку
            import traceback

            error_detail = traceback.format_exc()
            print(f"ERROR: {error_detail}")
            flash(f"Ошибка при обновлении товара: {str(e)}", "danger")

    product = models.get_product_by_id(product_id)
    history = models.get_product_history(product_id)
    return render_template("product_edit.html", product=product, history=history)


@app.route("/products/delete/<int:product_id>", methods=["POST"])
@login_required
@admin_required
def delete_product(product_id):
    """Удалить товар"""
    try:
        models.delete_product(product_id)
        flash("Товар удалён", "success")
    except Exception as e:
        flash(f"Ошибка при удалении товара: {str(e)}", "danger")

    return redirect(url_for("products"))


# ============ ОСТАТКИ ============


@app.route("/stock")
@login_required
def stock():
    """Текущие остатки"""
    stock_data = models.get_stock()
    return render_template("stock.html", stock=stock_data)


@app.route("/stock/low")
@login_required
def low_stock():
    """Товары с низким остатком"""
    low_stock_data = models.get_low_stock_products()
    return render_template("low_stock.html", stock=low_stock_data)


# ============ ОПЕРАЦИИ ПРИХОДА/РАСХОДА ============


@app.route("/movement/income", methods=["GET", "POST"])
@login_required
def movement_income():
    """Приход товара - связан с заказами поставщикам"""
    if request.method == "POST":
        try:
            supplier_order_id = request.form.get("supplier_order_id")
            product_id = int(request.form.get("product_id"))
            quantity = float(request.form.get("quantity"))
            comment = request.form.get("comment", "")

            # Если выбран заказ поставщика
            if supplier_order_id:
                order = models.get_supplier_order_by_id(int(supplier_order_id))
                comment = (
                    f"Заказ поставщику #{order['order_number']} - {comment}"
                    if comment
                    else f"Заказ поставщику #{order['order_number']}"
                )

                # Обновляем принятое количество в заказе
                models.update_supplier_order_item_received(
                    int(supplier_order_id), product_id, quantity, session["user_id"]
                )

            # Делаем приход товара
            success, message = models.add_movement(
                product_id, "income", quantity, comment, session["user_id"]
            )

            if success:
                flash(
                    "Приход товара оформлен. Статус заказа обновлён автоматически.",
                    "success",
                )
                return redirect(url_for("stock"))
            else:
                flash(message, "danger")
        except Exception as e:
            flash(f"Ошибка: {str(e)}", "danger")

    # Получаем открытые заказы поставщикам
    supplier_orders = models.get_open_supplier_orders()
    products = models.get_all_products()

    return render_template(
        "movement_income.html",
        title="Приход товара",
        movement_type="income",
        supplier_orders=supplier_orders,
        products=products,
    )


@app.route("/movement/outcome", methods=["GET", "POST"])
@login_required
def movement_outcome():
    """Расход товара - связан с заказами клиентов"""
    if request.method == "POST":
        try:
            customer_order_id = request.form.get("customer_order_id")
            product_id = int(request.form.get("product_id"))
            quantity = float(request.form.get("quantity"))
            comment = request.form.get("comment", "")

            # Если выбран заказ клиента
            if customer_order_id:
                order = models.get_customer_order_by_id(int(customer_order_id))
                comment = (
                    f"Заказ клиента #{order['order_number']} - {comment}"
                    if comment
                    else f"Заказ клиента #{order['order_number']}"
                )

                # Обновляем отгруженное количество в заказе
                models.update_customer_order_item_shipped(
                    int(customer_order_id), product_id, quantity, session["user_id"]
                )

            # Делаем расход товара
            success, message = models.add_movement(
                product_id, "outcome", quantity, comment, session["user_id"]
            )

            if success:
                flash(
                    "Расход товара оформлен. Статус заказа обновлён автоматически.",
                    "success",
                )
                return redirect(url_for("stock"))
            else:
                flash(message, "danger")
        except Exception as e:
            flash(f"Ошибка: {str(e)}", "danger")

    # Получаем открытые заказы клиентов
    customer_orders = models.get_open_customer_orders()
    products = models.get_all_products()

    return render_template(
        "movement_outcome.html",
        title="Расход товара",
        movement_type="outcome",
        customer_orders=customer_orders,
        products=products,
    )


# ============ ОТЧЁТЫ ============


@app.route("/reports/movements")
@login_required
def reports_movements():
    """Журнал движений"""
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    product_id = request.args.get("product_id")

    movements = models.get_movements(date_from, date_to, product_id)
    products = models.get_all_products()

    return render_template("reports.html", movements=movements, products=products)


# ============ ЗАКАЗЫ ПОСТАВЩИКАМ ============


@app.route("/supplier_orders")
@login_required
def supplier_orders():
    """Список заказов поставщикам"""
    orders = models.get_all_supplier_orders()
    return render_template("supplier_orders.html", orders=orders)


@app.route("/supplier_orders/create", methods=["GET", "POST"])
@admin_required
def create_supplier_order():
    """Создать заказ поставщику"""
    if request.method == "POST":
        try:
            order_number = request.form.get("order_number")
            supplier_name = request.form.get("supplier_name")
            order_date = request.form.get("order_date")
            expected_date = request.form.get("expected_date")
            notes = request.form.get("notes", "")

            # Собираем товары
            product_ids = request.form.getlist("product_id[]")
            quantities = request.form.getlist("quantity[]")
            prices = request.form.getlist("price[]")

            items = []
            for i in range(len(product_ids)):
                if product_ids[i] and quantities[i]:
                    items.append(
                        {
                            "product_id": int(product_ids[i]),
                            "quantity": float(quantities[i]),
                            "price": float(prices[i]) if prices[i] else 0,
                        }
                    )

            models.create_supplier_order(
                order_number,
                supplier_name,
                order_date,
                expected_date,
                notes,
                items,
                session["user_id"],
            )
            flash("Заказ поставщику создан", "success")
            return redirect(url_for("supplier_orders"))
        except Exception as e:
            flash(f"Ошибка: {str(e)}", "danger")

    products = models.get_all_products()
    return render_template(
        "supplier_order_form.html", products=products, now=datetime.now()
    )


@app.route("/supplier_orders/<int:order_id>")
@login_required
def view_supplier_order(order_id):
    """Просмотр заказа поставщику"""
    order = models.get_supplier_order_by_id(order_id)
    return render_template("supplier_order_view.html", order=order)


@app.route("/supplier_orders/<int:order_id>/status", methods=["POST"])
@login_required
def update_supplier_order_status(order_id):
    """Обновить статус заказа поставщику"""
    try:
        status = request.form.get("status")
        models.update_supplier_order_status(order_id, status, session["user_id"])
        flash("Статус обновлён", "success")
    except Exception as e:
        flash(f"Ошибка: {str(e)}", "danger")
    return redirect(url_for("view_supplier_order", order_id=order_id))


# ============ ЗАКАЗЫ ОТ КЛИЕНТОВ ============


@app.route("/customer_orders")
@login_required
def customer_orders():
    """Список заказов от клиентов"""
    orders = models.get_all_customer_orders()
    return render_template("customer_orders.html", orders=orders)


@app.route("/api/customer_order/<int:order_id>/items")
@login_required
def get_customer_order_items(order_id):
    """API для получения товаров из заказа клиента"""
    from flask import jsonify

    order = models.get_customer_order_by_id(order_id)
    if not order:
        return jsonify({"error": "Заказ не найден"}), 404

    items = []
    for item in order["order_items"]:
        remaining = float(item["quantity"]) - float(item["shipped_quantity"])
        if remaining > 0:  # Показываем только неотгруженные
            items.append(
                {
                    "id": item["id"],
                    "product_id": item["product_id"],
                    "sku": item["sku"],
                    "name": item["name"],
                    "unit": item["unit"],
                    "quantity": float(item["quantity"]),
                    "shipped_quantity": float(item["shipped_quantity"]),
                    "remaining": remaining,
                    "stock_quantity": (
                        float(item["stock_quantity"]) if item["stock_quantity"] else 0
                    ),
                }
            )

    return jsonify(
        {
            "order_number": order["order_number"],
            "customer_name": order["customer_name"],
            "items": items,
        }
    )


@app.route("/customer_orders/create", methods=["GET", "POST"])
@login_required
def create_customer_order():
    """Создать заказ от клиента"""
    if request.method == "POST":
        try:
            order_number = request.form.get("order_number")
            customer_name = request.form.get("customer_name")
            order_date = request.form.get("order_date")
            deadline_date = request.form.get("deadline_date")
            notes = request.form.get("notes", "")

            # Собираем товары
            product_ids = request.form.getlist("product_id[]")
            quantities = request.form.getlist("quantity[]")

            items = []
            for i in range(len(product_ids)):
                if product_ids[i] and quantities[i]:
                    items.append(
                        {
                            "product_id": int(product_ids[i]),
                            "quantity": float(quantities[i]),
                        }
                    )

            models.create_customer_order(
                order_number,
                customer_name,
                order_date,
                deadline_date,
                notes,
                items,
                session["user_id"],
            )
            flash("Заказ от клиента создан", "success")
            return redirect(url_for("customer_orders"))
        except Exception as e:
            flash(f"Ошибка: {str(e)}", "danger")

    products = models.get_all_products()
    return render_template(
        "customer_order_form.html", products=products, now=datetime.now()
    )


@app.route("/customer_orders/<int:order_id>")
@login_required
def view_customer_order(order_id):
    """Просмотр заказа клиента"""
    order = models.get_customer_order_by_id(order_id)
    return render_template("customer_order_view.html", order=order)


@app.route("/customer_orders/<int:order_id>/status", methods=["POST"])
@login_required
def update_customer_order_status(order_id):
    """Обновить статус заказа клиента"""
    try:
        status = request.form.get("status")
        models.update_customer_order_status(order_id, status, session["user_id"])
        flash("Статус обновлён", "success")
    except Exception as e:
        flash(f"Ошибка: {str(e)}", "danger")
    return redirect(url_for("view_customer_order", order_id=order_id))


@app.route("/reports/movements/export")
@login_required
def export_movements():
    """Экспорт журнала движений в CSV"""
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    product_id = request.args.get("product_id")

    movements = models.export_movements_to_csv(date_from, date_to, product_id)

    # Создаём CSV в памяти
    si = StringIO()
    # Для русского Excel используем точку с запятой как разделитель
    writer = csv.writer(si, delimiter=";", lineterminator="\n")

    # Заголовки
    writer.writerow(
        ["Дата", "Тип", "Артикул", "Товар", "Количество", "Пользователь", "Комментарий"]
    )

    # Данные
    for m in movements:
        writer.writerow(
            [
                m["movement_date"].strftime("%d.%m.%Y %H:%M"),
                "Приход" if m["type"] == "income" else "Расход",
                m["sku"],
                m["product_name"],
                str(m["quantity"]),
                m["user_login"] or "-",
                m["comment"] or "-",
            ]
        )

    # Получаем содержимое
    output = si.getvalue()
    si.close()

    # Добавляем BOM для UTF-8 (чтобы Excel понял кодировку)
    output_with_bom = "\ufeff" + output

    # Кодируем в UTF-8
    output_bytes = output_with_bom.encode("utf-8")

    response = make_response(output_bytes)
    response.headers["Content-Disposition"] = (
        "attachment; filename=movements_export.csv"
    )
    response.headers["Content-Type"] = "text/csv; charset=utf-8"

    return response


# ============ ЗАПУСК ============

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
