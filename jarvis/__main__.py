"""python -m jarvis --port 8340"""
import argparse
import uvicorn

def main():
    parser = argparse.ArgumentParser(description="Jarvis local server")
    parser.add_argument("--port", type=int, default=8340)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("jarvis.server:app", host=args.host, port=args.port, reload=args.reload, access_log=False)

if __name__ == "__main__":
    main()
