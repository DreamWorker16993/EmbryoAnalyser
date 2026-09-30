package fijiagent;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.prefs.AbstractPreferences;
import java.util.prefs.Preferences;
import java.util.prefs.PreferencesFactory;

/** Isolate headless agent preferences from the Windows user registry. */
public final class MemoryPreferencesFactory implements PreferencesFactory {
    private final Preferences user = new Node(null, "");
    private final Preferences system = new Node(null, "");
    public Preferences userRoot() { return user; }
    public Preferences systemRoot() { return system; }
    private static final class Node extends AbstractPreferences {
        private final Map<String,String> values = new ConcurrentHashMap<>();
        private final Map<String,Node> children = new ConcurrentHashMap<>();
        Node(AbstractPreferences parent, String name) { super(parent, name); }
        protected void putSpi(String key, String value) { values.put(key, value); }
        protected String getSpi(String key) { return values.get(key); }
        protected void removeSpi(String key) { values.remove(key); }
        protected void removeNodeSpi() {
            values.clear(); children.clear();
            if (parent() instanceof Node) ((Node)parent()).children.remove(name());
        }
        protected String[] keysSpi() { return values.keySet().toArray(new String[0]); }
        protected String[] childrenNamesSpi() { return children.keySet().toArray(new String[0]); }
        protected AbstractPreferences childSpi(String name) {
            return children.computeIfAbsent(name, n -> new Node(this, n));
        }
        protected void syncSpi() { }
        protected void flushSpi() { }
    }
}
