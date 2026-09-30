from pathlib import Path
import os

ROOT = Path(__file__).resolve().parent
FIJI = Path(r'C:\Users\ethan\Desktop\Fiji')
JAVA = FIJI / 'java/win64/zulu21.42.19-ca-jdk21.0.7-win_x64'
SERVER = ROOT / '.venv/Scripts/fiji-mcp-server.exe'

def configure():
    os.environ['FIJI_PATH'] = str(FIJI)
    os.environ['FIJI_MODE'] = 'headless'
    os.environ['FIJI_JAVA_HOME'] = str(JAVA)
    os.environ['JAVA_HOME'] = str(JAVA)
    os.environ['PYTHONUNBUFFERED'] = '1'
    os.environ['PYTHONUTF8'] = '1'
    return dict(os.environ)
