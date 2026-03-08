import asyncio
import importlib
import os
import sys


async def load_and_run_plugins():
    from shared_client import start_client
    await start_client()
    plugin_dir = "plugins"
    plugins = [f[:-3] for f in os.listdir(plugin_dir) if f.endswith(".py") and f != "__init__.py"]

    for plugin in plugins:
        module = importlib.import_module(f"plugins.{plugin}")
        if hasattr(module, f"run_{plugin}_plugin"):
            print(f"Running {plugin} plugin...")
            await getattr(module, f"run_{plugin}_plugin")()


async def main():
    await load_and_run_plugins()
    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        from shared_client import client, app, userbot
        from config import STRING
        try:
            await app.stop()
        except Exception:
            pass
        if STRING:
            try:
                await userbot.stop()
            except Exception:
                pass
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    print("Starting clients ...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    except Exception as e:
        print(e)
        sys.exit(1)
