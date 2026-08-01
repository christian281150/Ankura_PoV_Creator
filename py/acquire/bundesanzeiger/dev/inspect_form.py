"""Quick diagnostic: dumps all input/button attributes on the UR homepage."""
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        page = await browser.new_page()
        await page.goto("https://www.unternehmensregister.de/de", timeout=15000)
        await page.wait_for_load_state("domcontentloaded")

        data = await page.evaluate("""
            () => {
                const results = [];
                document.querySelectorAll('input, button, select').forEach(el => {
                    results.push({
                        tag:         el.tagName,
                        type:        el.type || '',
                        id:          el.id || '',
                        name:        el.name || '',
                        placeholder: el.placeholder || '',
                        value:       el.value || '',
                        className:   el.className || '',
                        visible:     el.offsetParent !== null
                    });
                });
                return results;
            }
        """)

        print(f"\n{'TAG':<8} {'TYPE':<10} {'ID':<40} {'NAME':<30} {'PLACEHOLDER':<25} {'CLASS'}")
        print("-" * 140)
        for el in data:
            print(f"{el['tag']:<8} {el['type']:<10} {el['id']:<40} {el['name']:<30} {el['placeholder']:<25} {el['className'][:40]}")

        await browser.close()

asyncio.run(main())
