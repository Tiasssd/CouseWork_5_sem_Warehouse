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
import models
import csv


app = Flask(__name__)
app.config.from_object(Config)

# ============ ДЕКОРАТОРЫ ============123


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
    """Приход товара"""
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity = float(request.form.get("quantity"))
        comment = request.form.get("comment", "")

        success, message = models.add_movement(
            product_id, "income", quantity, comment, session["user_id"]
        )

        if success:
            flash(message, "success")
            return redirect(url_for("stock"))
        else:
            flash(message, "danger")

    products = models.get_all_products()
    return render_template(
        "movement_form.html",
        products=products,
        movement_type="income",
        title="Приход товара",
    )


@app.route("/movement/outcome", methods=["GET", "POST"])
@login_required
def movement_outcome():
    """Расход товара"""
    if request.method == "POST":
        product_id = int(request.form.get("product_id"))
        quantity = float(request.form.get("quantity"))
        comment = request.form.get("comment", "")

        success, message = models.add_movement(
            product_id, "outcome", quantity, comment, session["user_id"]
        )

        if success:
            flash(message, "success")
            return redirect(url_for("stock"))
        else:
            flash(message, "danger")

    products = models.get_all_products()
    return render_template(
        "movement_form.html",
        products=products,
        movement_type="outcome",
        title="Расход товара",
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
                str(m["quantity"]),  # Преобразуем в строку для корректного отображения
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
