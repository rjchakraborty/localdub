"""Own a loopback-only desktop service on an available port."""
import asyncio
import json
import os
from pathlib import Path
import socket

import uvicorn


async def serve():
    workspace=Path(os.environ['DUBBING_DESKTOP_WORKSPACE']).resolve()
    if not workspace.is_dir():raise RuntimeError('Selected workspace is unavailable')
    os.environ['DUBBING_HOME']=str(workspace/'Jobs')
    os.environ['HF_HOME']=str(workspace/'Models')
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.bind(('127.0.0.1',0));sock.listen(128);sock.setblocking(False)
    port=sock.getsockname()[1]
    os.environ['DUBBING_DESKTOP_PORT']=str(port)
    configuration=uvicorn.Config('dubbing.server:app',host='127.0.0.1',port=port,log_level='warning',access_log=False)
    server=uvicorn.Server(configuration)
    task=asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            if task.done():await task;raise RuntimeError('Local service did not start')
            await asyncio.sleep(.05)
        print(json.dumps({'event':'server_ready','url':f'http://127.0.0.1:{port}'}),flush=True)
        await task
    finally:
        sock.close()


if __name__=='__main__':
    asyncio.run(serve())
