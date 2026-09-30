"""Project-only PyImageJ startup settings; loaded by this virtualenv's .pth file."""
import os
from pathlib import Path
import scyjava.config

JAVA = Path(r'C:\Users\ethan\Desktop\Fiji\java\win64\zulu21.42.19-ca-jdk21.0.7-win_x64')
os.environ['JAVA_HOME'] = str(JAVA)
scyjava.config.set_java_constraints(fetch='auto', version='21')
scyjava.config.add_kwargs(jvmpath=str(JAVA / 'bin/server/jvm.dll'))

# jgo 3.1 checks JAVA_HOME/bin/java without the Windows .exe suffix.
# This is the current Python process only; user/system PATH stays unchanged.
os.environ['PATH'] = str(JAVA / 'bin') + os.pathsep + os.environ.get('PATH', '')
# Keep Java dependency caches inside this project.
import sys
PROJECT = Path(sys.prefix).parent
os.environ['JGO_CACHE_DIR'] = str(PROJECT / 'java-cache')
os.environ['M2_REPO'] = str(PROJECT / 'maven-cache')
scyjava.config.set_cache_dir(PROJECT / 'java-cache')
scyjava.config.set_m2_repo(PROJECT / 'maven-cache')
# Resolve through the official SciJava repository, reachable on this network.
scyjava.config.add_repositories({'central': 'https://maven.scijava.org/content/groups/public'})
# The existing Fiji supplies the main Java libraries. Add only missing bridge JARs.
# Avoid Maven resolution at every startup; versions are pinned in bridge-jars/.
import imglyb
endpoint = 'net.imglib2:imglib2-imglyb:1.1.0'
if endpoint in scyjava.config.endpoints:
    scyjava.config.endpoints.remove(endpoint)
for name in ('imglib2-imglyb-1.1.0.jar', 'imglib2-unsafe-1.0.0.jar', 'bigdataviewer-vistools-1.0.0-beta-31.jar'):
    jar = PROJECT / 'bridge-jars' / name
    if not jar.is_file():
        raise RuntimeError(f'Missing project bridge dependency: {jar}')
    scyjava.config.add_classpath(str(jar))
# The agent's Java preferences are in-memory, never stored in Windows registry.
scyjava.config.add_classpath(str(PROJECT / 'java-support'))
scyjava.config.add_option('-Djava.util.prefs.PreferencesFactory=fijiagent.MemoryPreferencesFactory')
scyjava.config.add_option('-Duser.home=' + str(PROJECT / 'java-user-home'))
(PROJECT / 'java-user-home').mkdir(exist_ok=True)
