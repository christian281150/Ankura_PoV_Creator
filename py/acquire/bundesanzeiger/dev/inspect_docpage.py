"""Dumps buttons/links on the current browser page — run while document page is open."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        # Connect to the already-open Edge session via CDP if possible,
        # otherwise open a fresh page so user can navigate manually.
        browser = await p.chromium.launch(channel="msedge", headless=False)
        page = await browser.new_page()
        input("Navigate to the document page in this new window, then press ENTER here: ")

        data = await page.evaluate("""
            () => {
                const out = [];
                document.querySelectorAll('a, button').forEach(el => {
                    const txt = el.innerText.trim().replace(/\\n/g,' ').slice(0,60);
                    const href = el.getAttribute('href') || '';
                    const cls  = (el.className||'').slice(0,60);
                    const title = el.getAttribute('title') || '';
                    if (txt || href || title)
                        out.push({tag: el.tagName, txt, href, cls, title});
                });
                return out;
            }
        """)
        print(f"\n{'TAG':<8} {'TEXT':<40} {'TITLE':<25} {'HREF':<40} {'CLASS'}")
        print("-"*160)
        for el in data:
            print(f"{el['tag']:<8} {el['txt']:<40} {el['title']:<25} {el['href']:<40} {el['cls']}")
        await browser.close()

asyncio.run(main())
