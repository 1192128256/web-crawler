# WebCrawler - 智能网页爬虫

基于 Flask + Selenium 的可视化网页爬虫应用，支持动态页面渲染。

## 功能特性

- 自定义目标 URL 爬取
- Selenium 驱动，支持 JavaScript 动态渲染页面
- 自动提取页面文本、链接、图片
- 可配置爬取深度（最大页数）、等待时间
- 同域名自动发现并跟踪链接
- 实时进度展示
- 爬取结果可视化展示（概览/链接/图片/文本）
- 支持 JSON 格式导出
- 历史任务记录

## 环境要求

- Python 3.8+
- Google Chrome 浏览器（Selenium 需要）

## 安装与运行

```bash
# 1. 进入项目目录
cd web_crawler

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动应用
python app.py
```

启动后访问 http://127.0.0.1:5000 即可使用。

## 使用说明

1. 在输入框中填写目标网站 URL
2. 配置爬取参数（最大页数、等待时间、是否提取链接/图片）
3. 点击"开始爬取"
4. 等待爬取完成，查看结果
5. 可通过"导出 JSON"下载完整数据
