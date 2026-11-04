// Schlüsselverwaltung des Ratsassistenten: standardmäßig nur im Arbeitsspeicher (weg beim Neuladen).
// Nur auf ausdrücklichen Wunsch in sessionStorage (weg beim Schließen des Tabs); localStorage wird für
// Schlüssel nie verwendet.
const PREFIX = "ris-assistent-schluessel:";

function session() {
  try { return globalThis.sessionStorage ?? null; } catch (e) { return null; }
}

export function createKeyStore(storage = session()) {
  const memory = new Map();
  const read = (p) => { try { return storage?.getItem(PREFIX + p) ?? null; } catch (e) { return null; } };
  return {
    get(provider) { return memory.get(provider) ?? read(provider) ?? ""; },
    remembered(provider) { return read(provider) != null; },
    set(provider, key, { remember = false } = {}) {
      const k = String(key ?? "").trim();
      memory.set(provider, k);
      try {
        if (remember && k) storage?.setItem(PREFIX + provider, k);
        else storage?.removeItem(PREFIX + provider);
      } catch (e) { /* Speicher gesperrt: bleibt im Arbeitsspeicher */ }
    },
    clear(provider) {
      memory.delete(provider);
      try { storage?.removeItem(PREFIX + provider); } catch (e) { /* nichts zu löschen */ }
    },
    clearAll() {
      memory.clear();
      try {
        for (let i = (storage?.length ?? 0) - 1; i >= 0; i--) {
          const k = storage.key(i);
          if (k?.startsWith(PREFIX)) storage.removeItem(k);
        }
      } catch (e) { /* nichts zu löschen */ }
    },
  };
}
