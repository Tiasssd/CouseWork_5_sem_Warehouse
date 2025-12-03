import os

class Config:
    # Секретный ключ для Flask sessions (измени на свой!)
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Настройки MySQL
    MYSQL_HOST = 'localhost'
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''  # Пустой пароль для XAMPP по умолчанию
    MYSQL_DB = 'warehouse_app'
    MYSQL_CHARSET = 'utf8mb4'
    MYSQL_CURSORCLASS = 'DictCursor'  # Возвращает результаты как словари
