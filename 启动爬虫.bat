@echo off
chcp 65001 >nul
title WebCrawler - 智能网页爬虫
cd /d "%~dp0"

echo ========================================
echo    WebCrawler 智能网页爬虫 启动中...
echo ========================================
echo.

pip install -r requirements.txt -q 2>nul

echo.
echo  即将在浏览器中打开...
echo  关闭此窗口即可停止服务
echo.

start http://127.0.0.1:5000

python app.py
pause
