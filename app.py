import csv
import io
import os
import shutil
import time
import threading
import uuid
import base64
from urllib.parse import urljoin, urlparse, quote

import requests as http_requests
from flask import Flask, render_template_string, request, jsonify, Response
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

IS_CONTAINER = os.environ.get("RENDER") or os.path.exists("/.dockerenv")

app = Flask(__name__)

crawl_tasks = {}
preview_pages = {}

PICKER_SCRIPT = """
(function(){
    document.addEventListener('click',function(e){
        e.preventDefault();e.stopPropagation();e.stopImmediatePropagation();
        var el=e.target;
        if(el.tagName==='HTML'||el.tagName==='BODY')return;
        var selector=_genSel(el);
        var text=(el.textContent||'').trim().substring(0,100);
        window.parent.postMessage({type:'element-selected',selector:selector,text:text,tagName:el.tagName.toLowerCase()},'*');
        el.style.outline='3px solid #4f46e5';el.style.outlineOffset='2px';
        setTimeout(function(){el.style.outline='';el.style.outlineOffset='';},1500);
    },true);
    var _lh=null;
    document.addEventListener('mouseover',function(e){
        if(_lh){_lh.style.outline='';_lh.style.outlineOffset='';_lh.style.cursor='';}
        var el=e.target;if(el.tagName==='HTML'||el.tagName==='BODY')return;
        el.style.outline='2px dashed #7c3aed';el.style.outlineOffset='1px';el.style.cursor='crosshair';_lh=el;
    },true);
    document.addEventListener('mouseout',function(e){
        if(_lh){_lh.style.outline='';_lh.style.outlineOffset='';_lh.style.cursor='';_lh=null;}
    },true);
    function _genSel(el){
        if(el.id)return '#'+el.id;
        var path=[],cur=el;
        while(cur&&cur.nodeType===1&&cur.tagName!=='BODY'&&cur.tagName!=='HTML'){
            var sel=cur.tagName.toLowerCase();
            if(cur.id){path.unshift('#'+cur.id);break;}
            if(cur.className&&typeof cur.className==='string'){
                var cls=cur.className.trim().split(/\\s+/).filter(function(c){return c.length>0&&c.length<50;});
                if(cls.length>0&&cls.length<=3){sel+='.'+cls.join('.');}
            }
            var par=cur.parentElement;
            if(par){var sibs=[];for(var i=0;i<par.children.length;i++){if(par.children[i].tagName===cur.tagName)sibs.push(par.children[i]);}
            if(sibs.length>1){sel+=':nth-of-type('+(sibs.indexOf(cur)+1)+')';}}
            path.unshift(sel);cur=cur.parentElement;if(path.length>=5)break;
        }
        return path.join(' > ');
    }
})();
"""

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WebCrawler - 智能网页爬虫</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
    <style>
:root {
    --primary: #4f46e5;
    --primary-hover: #4338ca;
    --bg: #f1f5f9;
    --card-bg: #ffffff;
}

body {
    background: var(--bg);
    font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
    min-height: 100vh;
}

.navbar {
    background: linear-gradient(135deg, var(--primary) 0%, #7c3aed 100%);
    box-shadow: 0 2px 12px rgba(79, 70, 229, 0.3);
}

.navbar-brand {
    font-size: 1.4rem;
    font-weight: 700;
    letter-spacing: 0.5px;
}

.card {
    border-radius: 12px;
    background: var(--card-bg);
}

.btn-primary {
    background: var(--primary);
    border-color: var(--primary);
    border-radius: 8px;
    font-weight: 600;
    transition: all 0.2s;
}

.btn-primary:hover {
    background: var(--primary-hover);
    border-color: var(--primary-hover);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.4);
}

.btn-primary:disabled {
    transform: none;
    box-shadow: none;
}

.form-control:focus,
.form-check-input:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 0.2rem rgba(79, 70, 229, 0.15);
}

.form-check-input:checked {
    background-color: var(--primary);
    border-color: var(--primary);
}

.progress-bar {
    background: linear-gradient(90deg, var(--primary), #7c3aed);
}

.nav-tabs .nav-link {
    color: #64748b;
    font-weight: 500;
    border: none;
    padding: 0.6rem 1.2rem;
    transition: color 0.2s;
}

.nav-tabs .nav-link.active {
    color: var(--primary);
    border-bottom: 2px solid var(--primary);
    background: transparent;
}

.nav-tabs .nav-link:hover:not(.active) {
    color: var(--primary-hover);
    border-color: transparent;
}

.page-card {
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.75rem;
    transition: box-shadow 0.2s;
}

.page-card:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.page-card .page-title {
    font-weight: 600;
    color: #1e293b;
    margin-bottom: 0.25rem;
}

.page-card .page-url {
    font-size: 0.82rem;
    color: #94a3b8;
    word-break: break-all;
}

.stat-box {
    background: linear-gradient(135deg, #f8fafc, #eef2ff);
    border-radius: 10px;
    padding: 1rem;
    text-align: center;
}

.stat-box .stat-num {
    font-size: 1.8rem;
    font-weight: 700;
    color: var(--primary);
}

.stat-box .stat-label {
    font-size: 0.85rem;
    color: #64748b;
}

.link-item {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    padding: 0.5rem 0;
    border-bottom: 1px solid #f1f5f9;
}

.link-item:last-child {
    border-bottom: none;
}

.link-item a {
    color: var(--primary);
    text-decoration: none;
    word-break: break-all;
    font-size: 0.9rem;
}

.link-item a:hover {
    text-decoration: underline;
}

.link-item .link-text {
    font-size: 0.8rem;
    color: #94a3b8;
}

.img-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
}

.img-card {
    border-radius: 8px;
    overflow: hidden;
    border: 1px solid #e2e8f0;
    transition: transform 0.2s;
}

.img-card:hover {
    transform: scale(1.03);
}

.img-card img {
    width: 100%;
    height: 120px;
    object-fit: cover;
    background: #f1f5f9;
}

.img-card .img-alt {
    font-size: 0.75rem;
    color: #64748b;
    padding: 4px 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.text-preview {
    background: #f8fafc;
    border-radius: 8px;
    padding: 1rem;
    margin-bottom: 0.75rem;
    font-size: 0.88rem;
    line-height: 1.7;
    color: #334155;
    max-height: 300px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-word;
}

.text-preview-title {
    font-weight: 600;
    color: var(--primary);
    margin-bottom: 0.5rem;
}

.history-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    background: white;
    cursor: pointer;
    transition: box-shadow 0.2s;
}

.history-item:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

.spin {
    display: inline-block;
    animation: spin 1s linear infinite;
}

.empty-state {
    text-align: center;
    padding: 3rem;
    color: #94a3b8;
}

.empty-state i {
    font-size: 3rem;
    margin-bottom: 1rem;
    display: block;
}

.page-selector {
    cursor: pointer;
    background: #f8fafc;
    border-radius: 8px;
    padding: 0.5rem 0.75rem;
    margin-bottom: 0.5rem;
    border: 1px solid #e2e8f0;
    transition: all 0.15s;
}

.page-selector:hover,
.page-selector.active {
    background: #eef2ff;
    border-color: var(--primary);
}

.mode-tabs .nav-link {
    font-size: 1.05rem;
    padding: 0.7rem 1.4rem;
    font-weight: 600;
    border-radius: 8px !important;
    color: #64748b;
    transition: all 0.2s;
}
.mode-tabs .nav-link.active {
    background: var(--primary) !important;
    color: white !important;
    box-shadow: 0 2px 8px rgba(79, 70, 229, 0.3);
}
.preview-container {
    border: 2px solid #e2e8f0;
    border-radius: 10px;
    overflow: hidden;
    background: white;
}
.preview-container iframe {
    width: 100%;
    height: 500px;
    border: none;
}
.rule-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.75rem;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    margin-bottom: 0.5rem;
    background: white;
    flex-wrap: wrap;
}
.rule-item code {
    flex: 1;
    font-size: 0.82rem;
    color: #7c3aed;
    word-break: break-all;
    min-width: 120px;
}
.targeted-results-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.88rem;
}
.targeted-results-table th,
.targeted-results-table td {
    padding: 0.5rem 0.75rem;
    border: 1px solid #e2e8f0;
    max-width: 300px;
    overflow: hidden;
    text-overflow: ellipsis;
}
.targeted-results-table th {
    background: #f8fafc;
    font-weight: 600;
    position: sticky;
    top: 0;
}
.targeted-results-table tr:hover td {
    background: #faf5ff;
}

.video-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
}
.video-card {
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    overflow: hidden;
    background: white;
    transition: box-shadow 0.2s;
}
.video-card:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}
.video-card video,
.video-card iframe {
    width: 100%;
    height: 200px;
    background: #0f172a;
    display: block;
}
.video-card .video-info {
    padding: 8px 12px;
}
.video-card .video-type {
    font-size: 0.75rem;
    color: white;
    padding: 2px 8px;
    border-radius: 4px;
    display: inline-block;
    margin-bottom: 4px;
}
.video-card .video-type.direct { background: #059669; }
.video-card .video-type.embed { background: #7c3aed; }
.video-card .video-url {
    font-size: 0.78rem;
    color: #94a3b8;
    word-break: break-all;
}
    </style>
</head>
<body>
    <nav class="navbar navbar-dark">
        <div class="container">
            <a class="navbar-brand" href="/">
                <i class="bi bi-bug"></i> WebCrawler
            </a>
            <span class="navbar-text text-light opacity-75">Selenium 驱动 · 智能网页数据采集</span>
        </div>
    </nav>

    <div class="container py-4">
        <ul class="nav nav-pills mode-tabs mb-4" role="tablist">
            <li class="nav-item">
                <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#modeGeneral">
                    <i class="bi bi-globe"></i> 通用爬取
                </button>
            </li>
            <li class="nav-item ms-2">
                <button class="nav-link" data-bs-toggle="pill" data-bs-target="#modeTargeted">
                    <i class="bi bi-crosshair"></i> 定向爬取
                </button>
            </li>
        </ul>
        <div class="tab-content">
        <div class="tab-pane fade show active" id="modeGeneral">
        <div class="card shadow-sm mb-4 border-0">
            <div class="card-body p-4">
                <h5 class="card-title mb-3"><i class="bi bi-gear"></i> 爬虫配置</h5>
                <div class="row g-3">
                    <div class="col-12">
                        <label class="form-label fw-semibold">目标 URL</label>
                        <div class="input-group input-group-lg">
                            <span class="input-group-text"><i class="bi bi-globe"></i></span>
                            <input type="url" id="urlInput" class="form-control"
                                   placeholder="https://example.com" autofocus>
                        </div>
                    </div>
                    <div class="col-md-3 col-6">
                        <label class="form-label">最大页数</label>
                        <input type="number" id="maxPages" class="form-control" value="5" min="1" max="50">
                    </div>
                    <div class="col-md-3 col-6">
                        <label class="form-label">等待时间(秒)</label>
                        <input type="number" id="waitTime" class="form-control" value="3" min="1" max="30">
                    </div>
                    <div class="col-md-3 col-6">
                        <div class="form-check form-switch mt-4">
                            <input class="form-check-input" type="checkbox" id="extractLinks" checked>
                            <label class="form-check-label" for="extractLinks">提取链接</label>
                        </div>
                    </div>
                    <div class="col-md-3 col-6">
                        <div class="form-check form-switch mt-4">
                            <input class="form-check-input" type="checkbox" id="extractImages" checked>
                            <label class="form-check-label" for="extractImages">提取图片</label>
                        </div>
                    </div>
                    <div class="col-md-3 col-6">
                        <div class="form-check form-switch mt-4">
                            <input class="form-check-input" type="checkbox" id="extractVideos" checked>
                            <label class="form-check-label" for="extractVideos">提取视频</label>
                        </div>
                    </div>
                    <div class="col-12">
                        <button id="startBtn" class="btn btn-primary btn-lg px-5" onclick="startCrawl()">
                            <i class="bi bi-play-fill"></i> 开始爬取
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div id="progressArea" class="card shadow-sm mb-4 border-0" style="display: none;">
            <div class="card-body p-4">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h5 class="card-title mb-0"><i class="bi bi-arrow-repeat spin"></i> 爬取进度</h5>
                    <span id="statusBadge" class="badge bg-warning">运行中</span>
                </div>
                <div class="progress mb-2" style="height: 8px;">
                    <div id="progressBar" class="progress-bar progress-bar-striped progress-bar-animated"
                         role="progressbar" style="width: 0%"></div>
                </div>
                <small id="progressText" class="text-muted">正在初始化...</small>
            </div>
        </div>

        <div id="resultsArea" style="display: none;">
            <div class="d-flex justify-content-between align-items-center mb-3">
                <h5 class="mb-0"><i class="bi bi-collection"></i> 爬取结果</h5>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-success" onclick="exportData()">
                        <i class="bi bi-download"></i> JSON
                    </button>
                    <button class="btn btn-outline-primary" onclick="exportCSV()">
                        <i class="bi bi-filetype-csv"></i> CSV
                    </button>
                </div>
            </div>

            <ul class="nav nav-tabs" id="resultTabs" role="tablist">
                <li class="nav-item">
                    <button class="nav-link active" data-bs-toggle="tab" data-bs-target="#tabOverview">
                        <i class="bi bi-list-ul"></i> 概览
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabLinks">
                        <i class="bi bi-link-45deg"></i> 链接
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabImages">
                        <i class="bi bi-image"></i> 图片
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabVideos">
                        <i class="bi bi-camera-video"></i> 视频
                    </button>
                </li>
                <li class="nav-item">
                    <button class="nav-link" data-bs-toggle="tab" data-bs-target="#tabText">
                        <i class="bi bi-file-text"></i> 文本
                    </button>
                </li>
            </ul>

            <div class="tab-content border border-top-0 rounded-bottom p-3 bg-white">
                <div class="tab-pane fade show active" id="tabOverview">
                    <div id="overviewContent"></div>
                </div>
                <div class="tab-pane fade" id="tabLinks">
                    <div id="linksContent"></div>
                </div>
                <div class="tab-pane fade" id="tabImages">
                    <div id="imagesContent"></div>
                </div>
                <div class="tab-pane fade" id="tabVideos">
                    <div id="videosContent"></div>
                </div>
                <div class="tab-pane fade" id="tabText">
                    <div id="textContent"></div>
                </div>
            </div>
        </div>

        <div id="historyArea" class="mt-4" style="display: none;">
            <h5><i class="bi bi-clock-history"></i> 历史任务</h5>
            <div id="historyList"></div>
        </div>
        </div>

        <div class="tab-pane fade" id="modeTargeted">
            <div class="card shadow-sm mb-4 border-0">
                <div class="card-body p-4">
                    <h5 class="card-title mb-3"><i class="bi bi-crosshair"></i> 定向爬取 - 指哪打哪</h5>
                    <p class="text-muted mb-3">加载页面预览 → 点击你想提取的元素 → 自动生成选择器 → 精确抓取数据</p>
                    <div class="row g-3">
                        <div class="col-12">
                            <label class="form-label fw-semibold">目标页面 URL</label>
                            <div class="input-group">
                                <span class="input-group-text"><i class="bi bi-globe"></i></span>
                                <input type="url" id="targetedUrl" class="form-control"
                                       placeholder="https://example.com/list">
                                <button id="previewBtn" class="btn btn-primary" onclick="loadPreview()">
                                    <i class="bi bi-eye"></i> 加载预览
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div id="previewArea" style="display:none;">
                <div class="card shadow-sm mb-4 border-0">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h5 class="card-title mb-0"><i class="bi bi-hand-index"></i> 页面预览</h5>
                            <span class="badge bg-primary"><i class="bi bi-crosshair"></i> 点击元素添加规则</span>
                        </div>
                        <div class="preview-container">
                            <iframe id="previewFrame" sandbox="allow-scripts allow-same-origin"></iframe>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm mb-4 border-0">
                    <div class="card-body p-4">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <h5 class="card-title mb-0"><i class="bi bi-list-check"></i> 提取规则</h5>
                            <button class="btn btn-outline-primary btn-sm" onclick="addRuleManual()">
                                <i class="bi bi-plus-lg"></i> 手动添加
                            </button>
                        </div>
                        <div id="rulesList">
                            <div class="empty-state py-3">
                                <i class="bi bi-hand-index" style="font-size:2rem"></i>
                                <p class="mb-0">点击预览页面中的元素添加规则</p>
                            </div>
                        </div>
                    </div>
                </div>

                <div class="card shadow-sm mb-4 border-0">
                    <div class="card-body p-4">
                        <h5 class="card-title mb-3"><i class="bi bi-files"></i> 多页配置 <small class="text-muted">(可选)</small></h5>
                        <label class="form-label">额外页面 URL（每行一个，留空则只爬当前页）</label>
                        <textarea id="additionalUrls" class="form-control" rows="3"
                                  placeholder="https://example.com/page/2&#10;https://example.com/page/3"></textarea>
                    </div>
                </div>

                <div class="text-center mb-4">
                    <button id="targetedStartBtn" class="btn btn-primary btn-lg px-5" onclick="startTargetedCrawl()">
                        <i class="bi bi-bullseye"></i> 开始定向爬取
                    </button>
                </div>

                <div id="targetedResultsArea" style="display:none;">
                    <div class="card shadow-sm mb-4 border-0">
                        <div class="card-body p-4">
                            <div class="d-flex justify-content-between align-items-center mb-3">
                                <h5 class="card-title mb-0"><i class="bi bi-table"></i> 提取结果</h5>
                                <button class="btn btn-outline-success btn-sm" onclick="exportTargetedResults()">
                                    <i class="bi bi-download"></i> 导出 JSON
                                </button>
                            </div>
                            <div class="table-responsive" style="max-height:500px;overflow:auto;">
                                <div id="targetedResultsContent"></div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        </div>
    </div>

    <footer class="text-center py-3 text-muted">
        <small>WebCrawler &copy; 2026 · Powered by Flask + Selenium</small>
    </footer>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
let currentTaskId = null;
let pollTimer = null;

function startCrawl() {
    const url = document.getElementById("urlInput").value.trim();
    if (!url) {
        showToast("请输入目标 URL");
        return;
    }

    const payload = {
        url: url,
        max_pages: parseInt(document.getElementById("maxPages").value) || 5,
        wait_time: parseInt(document.getElementById("waitTime").value) || 3,
        extract_links: document.getElementById("extractLinks").checked,
        extract_images: document.getElementById("extractImages").checked,
        extract_videos: document.getElementById("extractVideos").checked,
    };

    const btn = document.getElementById("startBtn");
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split"></i> 启动中...';

    fetch("/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    })
        .then((r) => r.json())
        .then((data) => {
            if (data.error) {
                showToast(data.error);
                resetBtn();
                return;
            }
            currentTaskId = data.task_id;
            showProgress();
            pollStatus();
        })
        .catch((e) => {
            showToast("请求失败: " + e.message);
            resetBtn();
        });
}

function resetBtn() {
    const btn = document.getElementById("startBtn");
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-play-fill"></i> 开始爬取';
}

function showProgress() {
    document.getElementById("progressArea").style.display = "block";
    document.getElementById("progressBar").style.width = "0%";
    document.getElementById("progressText").textContent = "正在初始化浏览器...";
    document.getElementById("statusBadge").className = "badge bg-warning";
    document.getElementById("statusBadge").textContent = "运行中";
}

function pollStatus() {
    if (!currentTaskId) return;

    fetch(`/api/status/${currentTaskId}`)
        .then((r) => r.json())
        .then((data) => {
            updateProgress(data);

            if (data.status === "running" || data.status === "pending") {
                pollTimer = setTimeout(pollStatus, 1500);
            } else {
                resetBtn();
                if (data.status === "completed") {
                    document.getElementById("statusBadge").className = "badge bg-success";
                    document.getElementById("statusBadge").textContent = "完成";
                    renderResults(data);
                } else if (data.status === "failed") {
                    document.getElementById("statusBadge").className = "badge bg-danger";
                    document.getElementById("statusBadge").textContent = "失败";
                    showToast("爬取失败: " + (data.error || "未知错误"));
                }
                loadHistory();
            }
        })
        .catch(() => {
            pollTimer = setTimeout(pollStatus, 3000);
        });
}

function updateProgress(data) {
    const bar = document.getElementById("progressBar");
    const text = document.getElementById("progressText");
    bar.style.width = data.progress + "%";
    text.textContent = `已爬取 ${data.total_pages} 个页面 (${data.progress}%)`;
}

function renderResults(data) {
    document.getElementById("resultsArea").style.display = "block";
    renderOverview(data);
    renderLinks(data);
    renderImages(data);
    renderVideos(data);
    renderText(data);
}

function renderOverview(data) {
    const results = data.results;
    let totalLinks = 0, totalImages = 0, totalVideos = 0;
    results.forEach((r) => {
        totalLinks += (r.links || []).length;
        totalImages += (r.images || []).length;
        totalVideos += (r.videos || []).length;
    });

    let html = `
    <div class="row g-3 mb-4">
        <div class="col-md col-6">
            <div class="stat-box">
                <div class="stat-num">${results.length}</div>
                <div class="stat-label">页面数</div>
            </div>
        </div>
        <div class="col-md col-6">
            <div class="stat-box">
                <div class="stat-num">${totalLinks}</div>
                <div class="stat-label">链接数</div>
            </div>
        </div>
        <div class="col-md col-6">
            <div class="stat-box">
                <div class="stat-num">${totalImages}</div>
                <div class="stat-label">图片数</div>
            </div>
        </div>
        <div class="col-md col-6">
            <div class="stat-box">
                <div class="stat-num">${totalVideos}</div>
                <div class="stat-label">视频数</div>
            </div>
        </div>
        <div class="col-md col-6">
            <div class="stat-box">
                <div class="stat-num">${data.status === "completed" ? "\u2713" : "\u2717"}</div>
                <div class="stat-label">状态</div>
            </div>
        </div>
    </div>
    <h6 class="mb-3">页面列表</h6>`;

    results.forEach((r, i) => {
        html += `
        <div class="page-card">
            <div class="page-title">${escapeHtml(r.title || "无标题")}</div>
            <div class="page-url">${escapeHtml(r.url)}</div>
            <div class="mt-1">
                <span class="badge bg-light text-dark me-1">
                    <i class="bi bi-link-45deg"></i> ${(r.links || []).length} 链接
                </span>
                <span class="badge bg-light text-dark me-1">
                    <i class="bi bi-image"></i> ${(r.images || []).length} 图片
                </span>
                <span class="badge bg-light text-dark">
                    <i class="bi bi-camera-video"></i> ${(r.videos || []).length} 视频
                </span>
                ${r.error ? '<span class="badge bg-danger ms-1">有错误</span>' : ""}
            </div>
        </div>`;
    });

    document.getElementById("overviewContent").innerHTML = html;
}

function renderLinks(data) {
    const container = document.getElementById("linksContent");
    let allLinks = [];
    data.results.forEach((r) => {
        (r.links || []).forEach((link) => {
            allLinks.push({ ...link, from: r.url });
        });
    });

    if (allLinks.length === 0) {
        container.innerHTML = `
        <div class="empty-state">
            <i class="bi bi-link-45deg"></i>
            <p>没有提取到链接</p>
        </div>`;
        return;
    }

    let html = `<p class="text-muted mb-3">共提取 ${allLinks.length} 个链接</p>`;
    allLinks.slice(0, 200).forEach((link) => {
        html += `
        <div class="link-item">
            <i class="bi bi-link-45deg text-primary"></i>
            <div>
                <a href="${escapeHtml(link.url)}" target="_blank">${escapeHtml(link.text || link.url)}</a>
                <div class="link-text">来源: ${escapeHtml(truncate(link.from, 80))}</div>
            </div>
        </div>`;
    });

    if (allLinks.length > 200) {
        html += `<p class="text-muted text-center mt-2">仅显示前 200 条，完整数据请导出 JSON</p>`;
    }

    container.innerHTML = html;
}

function renderImages(data) {
    const container = document.getElementById("imagesContent");
    let allImages = [];
    data.results.forEach((r) => {
        (r.images || []).forEach((img) => allImages.push(img));
    });

    if (allImages.length === 0) {
        container.innerHTML = `
        <div class="empty-state">
            <i class="bi bi-image"></i>
            <p>没有提取到图片</p>
        </div>`;
        return;
    }

    let html = `<p class="text-muted mb-3">共提取 ${allImages.length} 张图片</p><div class="img-grid">`;
    allImages.slice(0, 100).forEach((img) => {
        const proxySrc = "/api/image_proxy?url=" + encodeURIComponent(img.src);
        html += `
        <div class="img-card">
            <img src="${proxySrc}" alt="${escapeHtml(img.alt)}" loading="lazy"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22160%22 height=%22120%22><rect fill=%22%23f1f5f9%22 width=%22160%22 height=%22120%22/><text fill=%22%2394a3b8%22 x=%2250%%22 y=%2250%%22 text-anchor=%22middle%22 dy=%22.3em%22>加载失败</text></svg>'">
            <div class="img-alt">${escapeHtml(img.alt || "无描述")}</div>
        </div>`;
    });
    html += "</div>";

    container.innerHTML = html;
}

function renderVideos(data) {
    const container = document.getElementById("videosContent");
    let allVideos = [];
    data.results.forEach((r) => {
        (r.videos || []).forEach((v) => allVideos.push(v));
    });

    if (allVideos.length === 0) {
        container.innerHTML = `
        <div class="empty-state">
            <i class="bi bi-camera-video"></i>
            <p>没有提取到视频</p>
        </div>`;
        return;
    }

    let html = `<p class="text-muted mb-3">共提取 ${allVideos.length} 个视频</p><div class="video-grid">`;
    allVideos.slice(0, 50).forEach((v, idx) => {
        const platform = v.platform || '';
        const title = v.title || '';
        const resolution = v.resolution || '';

        if (v.type === "embed") {
            html += `
            <div class="video-card">
                <iframe src="${escapeHtml(v.src)}" allowfullscreen loading="lazy"
                        sandbox="allow-scripts allow-same-origin allow-presentation"></iframe>
                <div class="video-info">
                    <span class="video-type embed">嵌入视频</span>
                    ${title ? '<div style="font-weight:600;margin:2px 0">' + escapeHtml(truncate(title,50)) + '</div>' : ''}
                    <div class="video-url">${escapeHtml(platform)} ${escapeHtml(truncate(v.src, 60))}</div>
                </div>
            </div>`;
        } else if (platform === 'Bilibili' || v.src.includes('bilivideo') || v.src.includes('bilibili')) {
            const proxySrc = "/api/video_proxy?url=" + encodeURIComponent(v.src);
            const posterSrc = v.poster ? "/api/image_proxy?url=" + encodeURIComponent(v.poster) : "";
            html += `
            <div class="video-card">
                <video controls preload="metadata" src="${proxySrc}"
                       ${posterSrc ? 'poster="' + posterSrc + '"' : ''}
                       onerror="this.outerHTML='<div style=\\'height:200px;display:flex;align-items:center;justify-content:center;background:#0f172a;color:#94a3b8;flex-direction:column\\'><div>视频需通过代理加载</div><a href=\\'${escapeHtml(v.src)}\\' target=\\'_blank\\' style=\\'color:#818cf8;margin-top:8px\\'>打开原始链接</a></div>'">
                </video>
                <div class="video-info">
                    <span class="video-type" style="background:#00a1d6">Bilibili</span>
                    ${resolution ? '<span class="badge bg-light text-dark ms-1" style="font-size:0.7rem">' + escapeHtml(resolution) + '</span>' : ''}
                    ${title ? '<div style="font-weight:600;margin:2px 0">' + escapeHtml(truncate(title,50)) + '</div>' : ''}
                    <div class="video-url">
                        <a href="${escapeHtml(v.src)}" target="_blank">视频流地址</a>
                        ${v.audio ? ' · <a href="' + escapeHtml(v.audio) + '" target="_blank">音频流地址</a>' : ''}
                    </div>
                </div>
            </div>`;
        } else {
            const proxySrc = "/api/video_proxy?url=" + encodeURIComponent(v.src);
            const directSrc = escapeHtml(v.src);
            html += `
            <div class="video-card">
                <video id="vid_${idx}" controls preload="metadata" src="${directSrc}"
                       ${v.poster ? 'poster="/api/image_proxy?url=' + encodeURIComponent(v.poster) + '"' : ''}
                       onerror="if(!this.dataset.retried){this.dataset.retried='1';this.src='${proxySrc}';}">
                </video>
                <div class="video-info">
                    <span class="video-type direct">直链视频</span>
                    ${title ? '<div style="font-weight:600;margin:2px 0">' + escapeHtml(truncate(title,50)) + '</div>' : ''}
                    <div class="video-url">
                        <a href="${directSrc}" target="_blank">${escapeHtml(truncate(v.src, 60))}</a>
                    </div>
                </div>
            </div>`;
        }
    });
    html += "</div>";
    container.innerHTML = html;
}

function renderText(data) {
    const container = document.getElementById("textContent");
    if (data.results.length === 0) {
        container.innerHTML = `
        <div class="empty-state">
            <i class="bi bi-file-text"></i>
            <p>没有提取到文本内容</p>
        </div>`;
        return;
    }

    let html = `
    <div class="card border mb-3" style="border-radius:10px">
        <div class="card-body py-2 px-3">
            <div class="d-flex align-items-center flex-wrap gap-2">
                <strong style="font-size:0.9rem"><i class="bi bi-filetype-csv"></i> 导出为 CSV 数据集</strong>
                <div class="vr mx-1"></div>
                <div class="form-check form-check-inline mb-0">
                    <input class="form-check-input" type="checkbox" id="csvUrl" checked>
                    <label class="form-check-label" for="csvUrl" style="font-size:0.85rem">URL</label>
                </div>
                <div class="form-check form-check-inline mb-0">
                    <input class="form-check-input" type="checkbox" id="csvTitle" checked>
                    <label class="form-check-label" for="csvTitle" style="font-size:0.85rem">标题</label>
                </div>
                <div class="form-check form-check-inline mb-0">
                    <input class="form-check-input" type="checkbox" id="csvText" checked>
                    <label class="form-check-label" for="csvText" style="font-size:0.85rem">文本内容</label>
                </div>
                <div class="form-check form-check-inline mb-0">
                    <input class="form-check-input" type="checkbox" id="csvDesc">
                    <label class="form-check-label" for="csvDesc" style="font-size:0.85rem">页面描述</label>
                </div>
                <div class="form-check form-check-inline mb-0">
                    <input class="form-check-input" type="checkbox" id="csvKeywords">
                    <label class="form-check-label" for="csvKeywords" style="font-size:0.85rem">关键词</label>
                </div>
                <div class="form-check form-check-inline mb-0">
                    <input class="form-check-input" type="checkbox" id="csvCounts">
                    <label class="form-check-label" for="csvCounts" style="font-size:0.85rem">统计数</label>
                </div>
                <div class="vr mx-1"></div>
                <select id="csvSep" class="form-select form-select-sm" style="width:auto;font-size:0.85rem">
                    <option value="paragraph">保留换行</option>
                    <option value="single_line">合并为单行</option>
                    <option value="space">空格分隔</option>
                </select>
                <button class="btn btn-success btn-sm" onclick="exportCSV()">
                    <i class="bi bi-download"></i> 下载 CSV
                </button>
            </div>
        </div>
    </div>`;

    data.results.forEach((r) => {
        html += `
        <div class="text-preview-title">${escapeHtml(r.title || "无标题")}</div>
        <div class="text-preview">${escapeHtml(r.text_content || "（无文本内容）")}</div>`;
    });

    container.innerHTML = html;
}

function exportCSV() {
    if (!currentTaskId) { showToast("没有可导出的任务"); return; }
    let fields = [];
    if (document.getElementById("csvUrl").checked) fields.push("url");
    if (document.getElementById("csvTitle").checked) fields.push("title");
    if (document.getElementById("csvText").checked) fields.push("text_content");
    if (document.getElementById("csvDesc").checked) fields.push("meta_description");
    if (document.getElementById("csvKeywords").checked) fields.push("meta_keywords");
    if (document.getElementById("csvCounts").checked) fields.push("links_count", "images_count", "videos_count");
    if (fields.length === 0) { showToast("请至少选择一个导出字段"); return; }
    const sep = document.getElementById("csvSep").value;
    window.open(`/api/export_csv/${currentTaskId}?fields=${fields.join(",")}&sep=${sep}`, "_blank");
}

function exportData() {
    if (!currentTaskId) return;
    window.open(`/api/export/${currentTaskId}`, "_blank");
}

function loadHistory() {
    fetch("/api/tasks")
        .then((r) => r.json())
        .then((tasks) => {
            if (tasks.length === 0) return;
            document.getElementById("historyArea").style.display = "block";
            let html = "";
            tasks.reverse().forEach((t) => {
                const statusMap = {
                    completed: '<span class="badge bg-success">完成</span>',
                    running: '<span class="badge bg-warning">运行中</span>',
                    pending: '<span class="badge bg-secondary">等待中</span>',
                    failed: '<span class="badge bg-danger">失败</span>',
                };
                html += `
                <div class="history-item" onclick="loadTask('${t.task_id}')">
                    <div>
                        <strong>${escapeHtml(t.url)}</strong>
                        <div class="text-muted" style="font-size:0.82rem">
                            ${t.total_pages} 个页面 · ID: ${t.task_id}
                        </div>
                    </div>
                    ${statusMap[t.status] || ""}
                </div>`;
            });
            document.getElementById("historyList").innerHTML = html;
        });
}

function loadTask(taskId) {
    currentTaskId = taskId;
    fetch(`/api/status/${taskId}`)
        .then((r) => r.json())
        .then((data) => {
            if (data.status === "completed") {
                document.getElementById("progressArea").style.display = "block";
                document.getElementById("progressBar").style.width = "100%";
                document.getElementById("statusBadge").className = "badge bg-success";
                document.getElementById("statusBadge").textContent = "完成";
                document.getElementById("progressText").textContent =
                    `共爬取 ${data.total_pages} 个页面`;
                renderResults(data);
                window.scrollTo({ top: 0, behavior: "smooth" });
            }
        });
}

function escapeHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function truncate(str, max) {
    if (!str) return "";
    return str.length > max ? str.substring(0, max) + "..." : str;
}

function showToast(msg) {
    let toast = document.getElementById("appToast");
    if (!toast) {
        toast = document.createElement("div");
        toast.id = "appToast";
        toast.style.cssText =
            "position:fixed;top:20px;right:20px;z-index:9999;padding:12px 24px;" +
            "background:#1e293b;color:white;border-radius:8px;font-size:0.9rem;" +
            "box-shadow:0 4px 12px rgba(0,0,0,0.15);transition:opacity 0.3s;";
        document.body.appendChild(toast);
    }
    toast.textContent = msg;
    toast.style.opacity = "1";
    toast.style.display = "block";
    setTimeout(() => {
        toast.style.opacity = "0";
        setTimeout(() => (toast.style.display = "none"), 300);
    }, 3000);
}

document.getElementById("urlInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") startCrawl();
});

// ========== 定向爬取 ==========
let targetedRules = [];
let currentPreviewId = null;
let targetedResults = null;

function loadPreview() {
    const url = document.getElementById("targetedUrl").value.trim();
    if (!url) { showToast("请输入目标 URL"); return; }

    const btn = document.getElementById("previewBtn");
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split"></i> 加载中...';

    fetch("/api/preview_page", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url: url})
    })
    .then(r => r.json())
    .then(data => {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-eye"></i> 加载预览';
        if (data.error) { showToast("加载失败: " + data.error); return; }
        currentPreviewId = data.preview_id;
        document.getElementById("previewFrame").src = "/api/preview_html/" + data.preview_id;
        document.getElementById("previewArea").style.display = "block";
        showToast("页面已加载，点击元素添加提取规则");
    })
    .catch(e => {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-eye"></i> 加载预览';
        showToast("加载失败: " + e.message);
    });
}

window.addEventListener("message", function(e) {
    if (e.data && e.data.type === "element-selected") {
        const defaultName = e.data.tagName === "img" ? "图片"
                          : e.data.tagName === "a" ? "链接"
                          : "字段" + (targetedRules.length + 1);
        const fieldName = prompt(
            "已选中 <" + e.data.tagName + "> 元素\n" +
            "内容预览: \"" + e.data.text.substring(0, 60) + "\"\n" +
            "选择器: " + e.data.selector + "\n\n" +
            "请为此字段命名:",
            defaultName
        );
        if (fieldName) {
            let extract = "text";
            if (e.data.tagName === "img") extract = "src";
            else if (e.data.tagName === "a") extract = "href";
            targetedRules.push({ name: fieldName, selector: e.data.selector, extract: extract });
            renderRules();
        }
    }
});

function addRuleManual() {
    const selector = prompt("请输入 CSS 选择器 (如 h2.title, .item > a):");
    if (!selector) return;
    const name = prompt("请为此字段命名:", "字段" + (targetedRules.length + 1));
    if (!name) return;
    targetedRules.push({ name: name, selector: selector, extract: "text" });
    renderRules();
}

function renderRules() {
    const container = document.getElementById("rulesList");
    if (targetedRules.length === 0) {
        container.innerHTML = '<div class="empty-state py-3"><i class="bi bi-hand-index" style="font-size:2rem"></i><p class="mb-0">点击预览页面中的元素添加规则</p></div>';
        return;
    }
    let html = '';
    targetedRules.forEach((rule, i) => {
        html += `
        <div class="rule-item">
            <span class="badge bg-primary">${i + 1}</span>
            <input class="form-control form-control-sm" value="${escapeHtml(rule.name)}"
                   onchange="targetedRules[${i}].name=this.value" style="max-width:110px">
            <code class="flex-grow-1">${escapeHtml(rule.selector)}</code>
            <select class="form-select form-select-sm" style="max-width:90px"
                    onchange="targetedRules[${i}].extract=this.value">
                <option value="text" ${rule.extract==='text'?'selected':''}>文本</option>
                <option value="href" ${rule.extract==='href'?'selected':''}>链接</option>
                <option value="src" ${rule.extract==='src'?'selected':''}>图片</option>
                <option value="html" ${rule.extract==='html'?'selected':''}>HTML</option>
            </select>
            <button class="btn btn-outline-primary btn-sm" onclick="testRule(${i})" title="测试">
                <i class="bi bi-play"></i>
            </button>
            <button class="btn btn-outline-danger btn-sm" onclick="removeRule(${i})" title="删除">
                <i class="bi bi-trash"></i>
            </button>
        </div>`;
    });
    container.innerHTML = html;
}

function removeRule(i) { targetedRules.splice(i, 1); renderRules(); }

function testRule(i) {
    const rule = targetedRules[i];
    if (!currentPreviewId) { showToast("请先加载预览"); return; }
    fetch("/api/test_selector", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ preview_id: currentPreviewId, selector: rule.selector, extract: rule.extract })
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) { showToast(data.error); return; }
        let msg = "匹配到 " + data.count + " 个元素\n\n";
        data.samples.forEach((s, j) => { msg += (j+1) + ". " + s + "\n"; });
        alert(msg);
    })
    .catch(e => showToast("测试失败: " + e.message));
}

function startTargetedCrawl() {
    if (targetedRules.length === 0) { showToast("请至少添加一条提取规则"); return; }
    const mainUrl = document.getElementById("targetedUrl").value.trim();
    if (!mainUrl) { showToast("请输入目标 URL"); return; }
    const extra = document.getElementById("additionalUrls").value.trim();
    let urls = [mainUrl];
    if (extra) { extra.split("\n").forEach(l => { l = l.trim(); if (l) urls.push(l); }); }

    const btn = document.getElementById("targetedStartBtn");
    btn.disabled = true;
    btn.innerHTML = '<i class="bi bi-hourglass-split"></i> 爬取中...';

    fetch("/api/targeted_crawl", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ urls: urls, rules: targetedRules })
    })
    .then(r => r.json())
    .then(data => {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-bullseye"></i> 开始定向爬取';
        if (data.error) { showToast(data.error); return; }
        targetedResults = data.results;
        renderTargetedResults(data);
        showToast("定向爬取完成，共提取 " + data.total + " 条数据");
    })
    .catch(e => {
        btn.disabled = false;
        btn.innerHTML = '<i class="bi bi-bullseye"></i> 开始定向爬取';
        showToast("爬取失败: " + e.message);
    });
}

function renderTargetedResults(data) {
    document.getElementById("targetedResultsArea").style.display = "block";
    const container = document.getElementById("targetedResultsContent");
    if (!data.results || data.results.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>没有提取到数据</p></div>';
        return;
    }
    const columns = targetedRules.map(r => r.name);
    let html = '<p class="text-muted mb-2">共提取 ' + data.results.length + ' 条数据</p>';
    html += '<table class="targeted-results-table"><thead><tr><th>#</th>';
    columns.forEach(col => { html += '<th>' + escapeHtml(col) + '</th>'; });
    html += '</tr></thead><tbody>';
    data.results.forEach((row, i) => {
        html += '<tr><td>' + (i + 1) + '</td>';
        columns.forEach(col => {
            let val = row[col] || '';
            if (val.length > 200) val = val.substring(0, 200) + '...';
            html += '<td>' + escapeHtml(val) + '</td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

function exportTargetedResults() {
    if (!targetedResults) return;
    const blob = new Blob([JSON.stringify(targetedResults, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'targeted_crawl_results.json';
    a.click();
}

loadHistory();
    </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# 爬虫任务模型
# ---------------------------------------------------------------------------

class CrawlTask:
    def __init__(self, task_id, url, max_pages=10, extract_images=True,
                 extract_links=True, extract_videos=True, wait_time=3):
        self.task_id = task_id
        self.url = url
        self.max_pages = max_pages
        self.extract_images = extract_images
        self.extract_links = extract_links
        self.extract_videos = extract_videos
        self.wait_time = wait_time
        self.status = "pending"
        self.progress = 0
        self.results = []
        self.error = None
        self.visited_urls = set()

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "url": self.url,
            "status": self.status,
            "progress": self.progress,
            "results": self.results,
            "error": self.error,
            "total_pages": len(self.results),
        }


# ---------------------------------------------------------------------------
# Selenium 驱动与爬取逻辑
# ---------------------------------------------------------------------------

def create_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    if IS_CONTAINER:
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--single-process")
        chrome_path = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        if chrome_path:
            chrome_options.binary_location = chrome_path
        chromedriver_path = shutil.which("chromedriver")
        if chromedriver_path:
            service = Service(chromedriver_path)
        else:
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
    else:
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())

    return webdriver.Chrome(service=service, options=chrome_options)


def extract_page_data(driver, url, task):
    """从单个页面提取数据"""
    data = {
        "url": url,
        "title": "",
        "text_content": "",
        "links": [],
        "images": [],
        "videos": [],
        "meta": {},
    }

    try:
        driver.get(url)
        WebDriverWait(driver, task.wait_time).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(1)

        data["title"] = driver.title or "无标题"

        soup = BeautifulSoup(driver.page_source, "lxml")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        data["text_content"] = "\n".join(lines[:200])

        for meta_tag in soup.find_all("meta"):
            name = meta_tag.get("name") or meta_tag.get("property", "")
            content = meta_tag.get("content", "")
            if name and content:
                data["meta"][name] = content

        if task.extract_links:
            seen = set()
            for a_tag in soup.find_all("a", href=True):
                href = urljoin(url, a_tag["href"])
                link_text = a_tag.get_text(strip=True) or href
                if href.startswith("http") and href not in seen:
                    seen.add(href)
                    data["links"].append({"url": href, "text": link_text[:100]})
            data["links"] = data["links"][:100]

        if task.extract_images:
            seen = set()
            for img_tag in soup.find_all("img"):
                src = (
                    img_tag.get("data-src")
                    or img_tag.get("data-original")
                    or img_tag.get("data-lazy-src")
                    or img_tag.get("data-actualsrc")
                    or img_tag.get("src")
                    or ""
                )
                if not src or src.startswith("data:"):
                    continue
                src = urljoin(url, src)
                alt = img_tag.get("alt", "")
                if src.startswith("http") and src not in seen:
                    seen.add(src)
                    data["images"].append({"src": src, "alt": alt})
            data["images"] = data["images"][:50]

        if task.extract_videos:
            seen = set()

            try:
                js_videos = driver.execute_script("""
                    var results = [];
                    document.querySelectorAll('video').forEach(function(v){
                        var src = v.currentSrc || v.src || '';
                        if(src && src.startsWith('http')){
                            results.push({src:src, poster:v.poster||'', type:'direct'});
                        }
                        v.querySelectorAll('source').forEach(function(s){
                            var ss = s.src || s.getAttribute('data-src') || '';
                            if(ss && ss.startsWith('http')){
                                results.push({src:ss, poster:v.poster||'', type:'direct'});
                            }
                        });
                    });
                    return results;
                """) or []
                for jv in js_videos:
                    src = jv.get("src", "")
                    if src and src not in seen and not src.startswith("blob:"):
                        seen.add(src)
                        data["videos"].append({
                            "src": src, "type": "direct",
                            "poster": jv.get("poster", ""), "platform": ""
                        })
            except Exception:
                pass

            domain = urlparse(url).netloc

            if "bilibili.com" in domain:
                try:
                    bili_info = driver.execute_script("""
                        var result = {videos:[], title:'', cover:''};
                        try {
                            if(window.__playinfo__){
                                var d = window.__playinfo__.data || {};
                                if(d.dash){
                                    var vlist = d.dash.video || [];
                                    if(vlist.length>0){
                                        result.videos.push({
                                            src: vlist[0].baseUrl || vlist[0].base_url || '',
                                            backup: (vlist[0].backupUrl || vlist[0].backup_url || [])[0] || '',
                                            width: vlist[0].width || 0,
                                            height: vlist[0].height || 0
                                        });
                                    }
                                    var alist = d.dash.audio || [];
                                    if(alist.length>0){
                                        result.audio = alist[0].baseUrl || alist[0].base_url || '';
                                    }
                                }
                                if(d.durl){
                                    d.durl.forEach(function(item){
                                        if(item.url) result.videos.push({src:item.url, backup:''});
                                    });
                                }
                            }
                        }catch(e){}
                        try {
                            if(window.__INITIAL_STATE__){
                                var vi = window.__INITIAL_STATE__.videoData || {};
                                result.title = vi.title || '';
                                result.cover = vi.pic || '';
                            }
                        }catch(e){}
                        return result;
                    """) or {}
                    bili_cover = bili_info.get("cover", "")
                    bili_title = bili_info.get("title", "")
                    bili_audio = bili_info.get("audio", "")
                    for bv in (bili_info.get("videos") or []):
                        src = bv.get("src", "") or bv.get("backup", "")
                        if src and src.startswith("http") and src not in seen:
                            seen.add(src)
                            res_label = ""
                            if bv.get("width") and bv.get("height"):
                                res_label = f"{bv['width']}x{bv['height']}"
                            data["videos"].append({
                                "src": src, "type": "direct",
                                "poster": bili_cover,
                                "platform": "Bilibili",
                                "title": bili_title,
                                "resolution": res_label,
                                "audio": bili_audio,
                            })
                except Exception:
                    pass

            elif "youtube.com" in domain or "youtu.be" in domain:
                try:
                    yt_id = driver.execute_script("""
                        var m = document.querySelector('meta[property="og:video:url"]');
                        if(m) return m.content;
                        var el = document.querySelector('ytd-watch-flexy');
                        if(el) return el.getAttribute('video-id');
                        return '';
                    """) or ""
                    if "embed" in yt_id:
                        embed_url = yt_id
                    elif yt_id:
                        embed_url = f"https://www.youtube.com/embed/{yt_id}"
                    else:
                        embed_url = ""
                    if embed_url and embed_url not in seen:
                        seen.add(embed_url)
                        data["videos"].append({
                            "src": embed_url, "type": "embed",
                            "poster": "", "platform": "YouTube"
                        })
                except Exception:
                    pass

            page_soup = BeautifulSoup(driver.page_source, "lxml")

            for video_tag in page_soup.find_all("video"):
                src = (
                    video_tag.get("src")
                    or video_tag.get("data-src")
                    or ""
                )
                if not src:
                    for source in video_tag.find_all("source"):
                        src = source.get("src") or source.get("data-src") or ""
                        if src:
                            break
                if not src or src.startswith(("blob:", "data:")):
                    continue
                src = urljoin(url, src)
                if src.startswith("http") and src not in seen:
                    seen.add(src)
                    poster = video_tag.get("poster", "")
                    if poster:
                        poster = urljoin(url, poster)
                    data["videos"].append({
                        "src": src, "type": "direct", "poster": poster, "platform": ""
                    })

            for meta_tag in page_soup.find_all("meta"):
                prop = meta_tag.get("property", "") or meta_tag.get("name", "")
                content = meta_tag.get("content", "")
                if content and prop in ("og:video", "og:video:url", "og:video:secure_url",
                                        "twitter:player:stream"):
                    video_src = urljoin(url, content)
                    if video_src.startswith("http") and video_src not in seen:
                        seen.add(video_src)
                        data["videos"].append({
                            "src": video_src, "type": "direct", "poster": "", "platform": ""
                        })

            VIDEO_PLATFORMS = {
                "youtube.com/embed": "YouTube",
                "youtube-nocookie.com/embed": "YouTube",
                "player.bilibili.com": "Bilibili",
                "player.youku.com": "Youku",
                "player.vimeo.com": "Vimeo",
                "v.qq.com": "腾讯视频",
                "open.iqiyi.com": "爱奇艺",
            }
            for iframe_tag in page_soup.find_all("iframe", src=True):
                iframe_src = iframe_tag.get("src") or ""
                if not iframe_src:
                    continue
                iframe_src = urljoin(url, iframe_src)
                platform = ""
                for pattern, name in VIDEO_PLATFORMS.items():
                    if pattern in iframe_src:
                        platform = name
                        break
                if platform and iframe_src not in seen:
                    seen.add(iframe_src)
                    data["videos"].append({
                        "src": iframe_src, "type": "embed",
                        "poster": "", "platform": platform
                    })

            VIDEO_EXTS = (".mp4", ".webm", ".ogg", ".m3u8", ".flv", ".avi", ".mov")
            for a_tag in page_soup.find_all("a", href=True):
                href = a_tag.get("href", "")
                if not href:
                    continue
                href_lower = href.lower().split("?")[0]
                if any(href_lower.endswith(ext) for ext in VIDEO_EXTS):
                    full_href = urljoin(url, href)
                    if full_href not in seen:
                        seen.add(full_href)
                        data["videos"].append({
                            "src": full_href, "type": "direct",
                            "poster": "", "platform": ""
                        })

            data["videos"] = data["videos"][:30]

    except Exception as e:
        data["error"] = str(e)

    return data


def run_crawl(task):
    """在后台线程中执行爬虫任务"""
    task.status = "running"
    driver = None
    try:
        driver = create_driver()
        urls_to_crawl = [task.url]

        while urls_to_crawl and len(task.results) < task.max_pages:
            current_url = urls_to_crawl.pop(0)
            if current_url in task.visited_urls:
                continue

            task.visited_urls.add(current_url)
            page_data = extract_page_data(driver, current_url, task)
            task.results.append(page_data)
            task.progress = int((len(task.results) / task.max_pages) * 100)

            if task.extract_links and len(task.results) < task.max_pages:
                base_domain = urlparse(task.url).netloc
                for link in page_data.get("links", []):
                    link_url = link["url"]
                    if (
                        urlparse(link_url).netloc == base_domain
                        and link_url not in task.visited_urls
                        and link_url not in urls_to_crawl
                    ):
                        urls_to_crawl.append(link_url)

        task.status = "completed"
        task.progress = 100

    except Exception as e:
        task.status = "failed"
        task.error = str(e)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Flask 路由
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/crawl", methods=["POST"])
def start_crawl():
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "请输入有效的 URL"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    task_id = str(uuid.uuid4())[:8]
    task = CrawlTask(
        task_id=task_id,
        url=url,
        max_pages=min(int(data.get("max_pages", 5)), 50),
        extract_images=data.get("extract_images", True),
        extract_links=data.get("extract_links", True),
        extract_videos=data.get("extract_videos", True),
        wait_time=int(data.get("wait_time", 3)),
    )
    crawl_tasks[task_id] = task

    thread = threading.Thread(target=run_crawl, args=(task,), daemon=True)
    thread.start()

    return jsonify({"task_id": task_id, "message": "爬虫任务已启动"})


@app.route("/api/status/<task_id>")
def get_status(task_id):
    task = crawl_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task.to_dict())


@app.route("/api/tasks")
def list_tasks():
    return jsonify([t.to_dict() for t in crawl_tasks.values()])


@app.route("/api/export/<task_id>")
def export_data(task_id):
    task = crawl_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404
    return jsonify(task.results), 200, {
        "Content-Disposition": f"attachment; filename=crawl_{task_id}.json"
    }


@app.route("/api/export_csv/<task_id>")
def export_csv(task_id):
    """将爬取的文本数据导出为 CSV，支持自定义字段"""
    task = crawl_tasks.get(task_id)
    if not task:
        return jsonify({"error": "任务不存在"}), 404

    fields = request.args.get("fields", "url,title,text_content")
    field_list = [f.strip() for f in fields.split(",") if f.strip()]

    separator = request.args.get("sep", "paragraph")

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)

    header_map = {
        "url": "URL", "title": "标题", "text_content": "文本内容",
        "links_count": "链接数", "images_count": "图片数",
        "videos_count": "视频数", "meta_description": "页面描述",
        "meta_keywords": "关键词",
    }
    writer.writerow([header_map.get(f, f) for f in field_list])

    for page in task.results:
        row = []
        for f in field_list:
            if f == "url":
                row.append(page.get("url", ""))
            elif f == "title":
                row.append(page.get("title", ""))
            elif f == "text_content":
                text = page.get("text_content", "")
                if separator == "single_line":
                    text = text.replace("\n", " ").replace("\r", " ")
                elif separator == "space":
                    text = " ".join(text.split())
                row.append(text)
            elif f == "links_count":
                row.append(str(len(page.get("links", []))))
            elif f == "images_count":
                row.append(str(len(page.get("images", []))))
            elif f == "videos_count":
                row.append(str(len(page.get("videos", []))))
            elif f == "meta_description":
                meta = page.get("meta", {})
                row.append(meta.get("description", meta.get("og:description", "")))
            elif f == "meta_keywords":
                row.append(page.get("meta", {}).get("keywords", ""))
            else:
                row.append("")
        writer.writerow(row)

    csv_data = output.getvalue()
    output.close()

    return Response(
        csv_data,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=crawl_{task_id}.csv"}
    )


@app.route("/api/preview_page", methods=["POST"])
def preview_page():
    """加载页面并注入元素选择器脚本"""
    data = request.get_json()
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "请输入 URL"}), 400
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    driver = None
    try:
        driver = create_driver()
        driver.get(url)
        WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(2)
        page_source = driver.page_source
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    soup = BeautifulSoup(page_source, "lxml")

    for tag in soup.find_all(["img", "script", "link", "source", "video", "audio"]):
        for attr in ("src", "href"):
            val = tag.get(attr)
            if val and not val.startswith(("http", "data:", "blob:", "javascript:")):
                tag[attr] = urljoin(url, val)

    for tag in soup.find_all("a"):
        href = tag.get("href")
        if href and not href.startswith(("http", "data:", "blob:", "javascript:", "#")):
            tag["href"] = urljoin(url, href)

    for tag in soup.find_all(True, {"style": True}):
        pass

    script_tag = soup.new_tag("script")
    script_tag.string = PICKER_SCRIPT
    if soup.body:
        soup.body.append(script_tag)

    picker_style = soup.new_tag("style")
    picker_style.string = "* { cursor: crosshair !important; } a { pointer-events: auto !important; }"
    if soup.head:
        soup.head.append(picker_style)

    preview_id = str(uuid.uuid4())[:8]
    preview_pages[preview_id] = str(soup)

    return jsonify({"preview_id": preview_id, "url": url})


@app.route("/api/preview_html/<preview_id>")
def get_preview_html(preview_id):
    html = preview_pages.get(preview_id)
    if not html:
        return "Preview expired", 404
    return Response(html, content_type="text/html; charset=utf-8")


@app.route("/api/test_selector", methods=["POST"])
def test_selector():
    """测试 CSS 选择器在预览页面上的匹配结果"""
    data = request.get_json()
    preview_id = data.get("preview_id")
    selector = data.get("selector", "")
    extract = data.get("extract", "text")

    html = preview_pages.get(preview_id)
    if not html:
        return jsonify({"error": "预览已过期，请重新加载"}), 404

    soup = BeautifulSoup(html, "lxml")
    try:
        elements = soup.select(selector)
    except Exception as e:
        return jsonify({"error": f"选择器无效: {e}"}), 400

    samples = []
    for el in elements[:20]:
        if extract == "href":
            samples.append(el.get("href", ""))
        elif extract == "src":
            samples.append(el.get("src", ""))
        elif extract == "html":
            samples.append(str(el)[:200])
        else:
            samples.append(el.get_text(strip=True)[:200])

    return jsonify({"count": len(elements), "samples": samples})


@app.route("/api/targeted_crawl", methods=["POST"])
def targeted_crawl_api():
    """按自定义规则定向爬取数据"""
    data = request.get_json()
    urls = data.get("urls", [])
    rules = data.get("rules", [])

    if not rules:
        return jsonify({"error": "请添加至少一条提取规则"}), 400
    if not urls:
        return jsonify({"error": "请提供至少一个 URL"}), 400

    driver = None
    results = []
    try:
        driver = create_driver()
        for page_url in urls[:50]:
            if not page_url.startswith(("http://", "https://")):
                page_url = "https://" + page_url
            driver.get(page_url)
            time.sleep(2)
            soup = BeautifulSoup(driver.page_source, "lxml")

            first_elements = soup.select(rules[0]["selector"])
            count = max(len(first_elements), 1)

            if count > 1:
                for i in range(count):
                    row = {}
                    for rule in rules:
                        els = soup.select(rule["selector"])
                        if i < len(els):
                            el = els[i]
                            ext = rule.get("extract", "text")
                            if ext == "href":
                                row[rule["name"]] = urljoin(page_url, el.get("href", ""))
                            elif ext == "src":
                                row[rule["name"]] = urljoin(page_url, el.get("src", ""))
                            elif ext == "html":
                                row[rule["name"]] = str(el)[:500]
                            else:
                                row[rule["name"]] = el.get_text(strip=True)
                        else:
                            row[rule["name"]] = ""
                    results.append(row)
            else:
                row = {}
                for rule in rules:
                    els = soup.select(rule["selector"])
                    if els:
                        el = els[0]
                        ext = rule.get("extract", "text")
                        if ext == "href":
                            row[rule["name"]] = urljoin(page_url, el.get("href", ""))
                        elif ext == "src":
                            row[rule["name"]] = urljoin(page_url, el.get("src", ""))
                        elif ext == "html":
                            row[rule["name"]] = str(el)[:500]
                        else:
                            row[rule["name"]] = el.get_text(strip=True)
                    else:
                        row[rule["name"]] = ""
                results.append(row)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    return jsonify({"results": results, "total": len(results)})


@app.route("/api/image_proxy")
def image_proxy():
    """代理请求图片，绕过防盗链"""
    img_url = request.args.get("url", "")
    if not img_url:
        return "Missing url", 400
    try:
        resp = http_requests.get(
            img_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": _get_referer(img_url),
            },
            timeout=10,
            stream=True,
        )
        content_type = resp.headers.get("Content-Type", "image/jpeg")
        return Response(resp.content, content_type=content_type)
    except Exception:
        return "Failed to load image", 502


REFERER_MAP = {
    "bilivideo": "https://www.bilibili.com/",
    "bilibili": "https://www.bilibili.com/",
    "googlevideo": "https://www.youtube.com/",
    "youtube": "https://www.youtube.com/",
    "youku": "https://www.youku.com/",
    "iqiyi": "https://www.iqiyi.com/",
    "qq.com": "https://v.qq.com/",
}


def _get_referer(target_url):
    """根据 CDN 域名自动匹配正确的 Referer"""
    for keyword, referer in REFERER_MAP.items():
        if keyword in target_url:
            return referer
    return f"{urlparse(target_url).scheme}://{urlparse(target_url).netloc}/"


@app.route("/api/video_proxy")
def video_proxy():
    """流式代理视频，支持 Range 请求（HTML5 播放器必需）"""
    video_url = request.args.get("url", "")
    if not video_url:
        return "Missing url", 400
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": _get_referer(video_url),
            "Origin": _get_referer(video_url).rstrip("/"),
        }
        range_header = request.headers.get("Range")
        if range_header:
            headers["Range"] = range_header

        resp = http_requests.get(video_url, headers=headers, timeout=60, stream=True)

        resp_headers = {
            "Content-Type": resp.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes",
        }
        for h in ("Content-Length", "Content-Range"):
            if h in resp.headers:
                resp_headers[h] = resp.headers[h]

        def stream():
            for chunk in resp.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk

        return Response(stream(), status=resp.status_code, headers=resp_headers)
    except Exception:
        return "Failed to load video", 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = not IS_CONTAINER
    app.run(host="0.0.0.0", port=port, debug=debug)
