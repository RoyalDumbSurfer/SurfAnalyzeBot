@echo off
echo ===============================
echo === SurfAnalyzeBot Launcher ===
echo ===============================

echo [✓] Удаляем lock-файл...
del bot.lock 2>nul

echo [✓] Активируем виртуальное окружение...
call venv\Scripts\activate

echo [✓] Запускаем бота...
python main.py
