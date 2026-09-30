from environment import configure
configure()
import faulthandler
faulthandler.dump_traceback_later(40, exit=True)
from fiji_mcp.bridge import get_ij
ij = get_ij()
print(ij.getVersion())
faulthandler.cancel_dump_traceback_later()
ij.dispose()
