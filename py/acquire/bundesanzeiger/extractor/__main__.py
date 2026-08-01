"""`python -m extractor` entry point."""
import asyncio
from .cli import main

if __name__ == "__main__":
    asyncio.run(main())
