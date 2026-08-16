"""渲染 HTML 线框为 PNG 预览（三档宽度 375/768/1440）"""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
HTML = BASE_DIR / "wireframes.html"
OUT = BASE_DIR / "preview"
OUT.mkdir(parents=True, exist_ok=True)

url = HTML.as_uri()  # file:///D:/...

viewports = {
    "1440": {"width": 1440, "height": 900},
    "768": {"width": 768, "height": 1024},
    "375": {"width": 375, "height": 812},
}

with sync_playwright() as p:
    # 优先系统 Chrome（channel="chrome"），无需单独下载 chromium
    try:
        browser = p.chromium.launch(channel="chrome", headless=True)
    except Exception as e:
        print("chrome 启动失败，回退默认 chromium：", e)
        browser = p.chromium.launch(headless=True)

    for name, vp in viewports.items():
        page = browser.new_page(viewport=vp)
        page.goto(url, wait_until="networkidle")
        # 等待样式渲染
        page.wait_for_timeout(500)
        out = OUT / f"wireframes-{name}.png"
        page.screenshot(path=str(out), full_page=True)
        print(f"已生成 {out} ({vp['width']}px)")
        page.close()

    browser.close()

print("完成")
