"""Рендерит дашборд в PDF через playwright chromium (уже установлен для hh-applicant-tool)."""

from common import BASE, HH_CONFIG
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from statistics_store import read_statistics,render_report,publish
import tempfile

SRC = BASE / 'hh-dashboard.html'
OUT = BASE / 'Разбор откликов hh.ru.pdf'


async def main():
    snapshot=read_statistics(BASE)
    with tempfile.NamedTemporaryFile(mode='w',suffix='.html',delete=False,encoding='utf-8') as file:
        file.write(render_report(BASE,'dashboard',export=True))
        rendered=Path(file.name)
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chromium")
        page = await b.new_page(viewport={"width": 1180, "height": 1400},
                                color_scheme="light", device_scale_factor=2)
        await page.goto(rendered.as_uri(), wait_until="load")
        await page.wait_for_timeout(1200)  # шрифты + отрисовка SVG
        h = await page.evaluate("document.querySelector('.wrap').scrollHeight + 48")
        temporary = OUT.with_suffix(".pdf.tmp")
        await page.pdf(path=str(temporary), print_background=True,
                       width="1180px", height=f"{h}px",
                       margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        temporary.chmod(0o600)
        temporary.replace(OUT)
        await b.close()
    rendered.unlink()
    publish(BASE,'pdf',{'source_generated_at':snapshot['dashboard']['gen'],'source_revision':snapshot['revision']})
    print("PDF:", OUT, OUT.stat().st_size, "байт")


asyncio.run(main())
