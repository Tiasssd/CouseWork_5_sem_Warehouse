# app.py - Главный файл Flask приложения

from flask import Flask, render_template, request, redirect, url_for, session, flash
from decimal import Decimal
from functools import wraps
from config import Config
import models

app = Flask(__name__)
app.config.from_object(Config)

# ============ ДЕКОРАТОР ДЛЯ АВТОРИЗАЦИИ ============


def login_required(f):
    """Декоратор для защиты роутов, требующих авторизации"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Пожалуйста, войдите в систему", "warning")
            return redirect(url_for("login"))
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
    """Главная панель с кнопками навигации"""
    return render_template("dashboard.html")


# ============ ТОВАРЫ ============


@app.route("/products")
@login_required
def products():
    """Список товаров"""
    products = models.get_all_products()
    return render_template("products.html", products=products)


@app.route("/products/add", methods=["POST"])
@login_required
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

            models.update_product(
                product_id, sku, name, category, unit, min_stock, price
            )
            flash("Товар успешно обновлён", "success")
            return redirect(url_for("products"))
        except Exception as e:
            flash(f"Ошибка при обновлении товара: {str(e)}", "danger")

    product = models.get_product_by_id(product_id)
    return render_template("product_edit.html", product=product)


@app.route("/products/delete/<int:product_id>", methods=["POST"])
@login_required
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


# ============ ЗАПУСК ============

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
