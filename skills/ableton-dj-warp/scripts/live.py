"""Send one command to the AbletonMCP Remote Script socket (127.0.0.1:9877) and print the JSON reply.

Usage:
  python3 -I live.py <command> '<json params>'
Examples:
  python3 -I live.py get_session_info '{}'
  python3 -I live.py get_track_info '{"track_index":2}'
  python3 -I live.py get_clip_warp '{"track_index":2,"clip_index":0}'
  python3 -I live.py set_clip_warp '{"track_index":2,"clip_index":0,"bpm":140,"downbeat_sec":0.0982,"warp_mode":6}'
  python3 -I live.py set_clip_markers '{"track_index":2,"clip_index":0,"looping":false,"start":0,"end":432}'
  python3 -I live.py create_audio_clip '{"track_index":2,"clip_index":0,"path":"/abs/file.mp3"}'
"""
import json
import socket
import sys

if len(sys.argv) < 2:
    sys.exit(__doc__)
cmd = sys.argv[1]
params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
s = socket.create_connection(("127.0.0.1", 9877), timeout=90)
s.sendall(json.dumps({"type": cmd, "params": params}).encode())
buf = b""
while True:
    chunk = s.recv(65536)
    if not chunk:
        break
    buf += chunk
    try:
        resp = json.loads(buf.decode())
        break
    except ValueError:
        continue
s.close()
print(json.dumps(resp, indent=1, ensure_ascii=False))
