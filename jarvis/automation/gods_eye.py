"""Direct local map launch, without language-model or desktop-automation latency."""
import asyncio
import os
from pathlib import Path
import subprocess
import httpx

BASE = 'http://127.0.0.1:4173'
SWITZERLAND_URL = BASE + '/?performance=efficient#v=2&lat=46.8&lon=8.23&alt=480000&heading=0&pitch=-65&style=normal&bloom=0&sharpen=0&map=esri-imagery&l=f.m&lo=f.e.0&sc=0'
USA_URL = BASE + '/?performance=efficient#v=2&lat=39&lon=-98&alt=6000000&heading=0&pitch=-65&style=normal&bloom=0&sharpen=0&map=esri-imagery&l=f.m&lo=f.e.0&sc=0'
_startup = asyncio.Lock()


async def ensure_running():
    async with _startup:
        async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
            try:
                response=await client.get(BASE)
                if response.status_code==200 and 'Eye View' in response.text:return
                raise RuntimeError('Port 4173 is occupied by a different application.')
            except httpx.TransportError:
                pass
        folder=Path(os.getenv('GODS_EYE_DIR',str(Path.home()/'Documents/Jarvis v4/gods-eye-view')))
        script=folder/'Start-GodsEye.ps1'
        if not script.is_file():raise RuntimeError("God's Eye View is not installed at its configured location.")
        exe=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        result=await asyncio.to_thread(subprocess.run,[str(exe),'-NoProfile','-ExecutionPolicy','Bypass','-File',str(script),'-NoBrowser'],
            cwd=str(folder),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=50,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError("God's Eye View could not start. Check its local server log.")
        async with httpx.AsyncClient(timeout=3,trust_env=False) as client:
            response=await client.get(BASE)
            if response.status_code!=200 or 'Eye View' not in response.text:raise RuntimeError('The map server is not ready.')


async def open_map(switzerland=False, usa=False):
    from jarvis.automation.website_launcher import open_in_chrome
    try:
        await ensure_running()
        await asyncio.to_thread(open_in_chrome,USA_URL if usa else SWITZERLAND_URL if switzerland else BASE+'/?performance=efficient')
        if usa:return 'Opening the USA with available live aircraft in Chrome.'
        return 'Opening Switzerland with available live aircraft in Chrome.' if switzerland else "Opening God's Eye View in Chrome."
    except (RuntimeError,OSError,subprocess.TimeoutExpired,httpx.HTTPError) as exc:
        return 'I could not open the map. '+str(exc)[:200]
