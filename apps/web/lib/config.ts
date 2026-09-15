/** Helpers for reading and writing dotted paths in a GenerationConfig object. */

export type ConfigObject = Record<string, unknown>;

export function getPath(source: ConfigObject, dotted: string): unknown {
  return dotted.split(".").reduce<unknown>((value, part) => {
    if (value && typeof value === "object") return (value as ConfigObject)[part];
    return undefined;
  }, source);
}

export function setPath(source: ConfigObject, dotted: string, value: unknown): ConfigObject {
  const parts = dotted.split(".");
  const next: ConfigObject = { ...source };
  let cursor = next;
  parts.forEach((part, index) => {
    if (index === parts.length - 1) {
      cursor[part] = value;
      return;
    }
    const existing = cursor[part];
    cursor[part] = existing && typeof existing === "object" ? { ...(existing as ConfigObject) } : {};
    cursor = cursor[part] as ConfigObject;
  });
  return next;
}

export function deepMerge(base: ConfigObject, overrides: ConfigObject): ConfigObject {
  const result: ConfigObject = { ...base };
  Object.entries(overrides).forEach(([key, value]) => {
    const existing = result[key];
    if (value && typeof value === "object" && !Array.isArray(value) && existing && typeof existing === "object") {
      result[key] = deepMerge(existing as ConfigObject, value as ConfigObject);
    } else {
      result[key] = value;
    }
  });
  return result;
}

/** Fields that differ from the defaults, as dotted paths. Used by the diff view. */
export function changedPaths(defaults: ConfigObject, current: ConfigObject, prefix = ""): string[] {
  const paths: string[] = [];
  const keys = new Set([...Object.keys(defaults ?? {}), ...Object.keys(current ?? {})]);
  keys.forEach((key) => {
    const dotted = prefix ? `${prefix}.${key}` : key;
    const left = (defaults ?? {})[key];
    const right = (current ?? {})[key];
    const bothObjects =
      left && right && typeof left === "object" && typeof right === "object" && !Array.isArray(left);
    if (bothObjects) {
      paths.push(...changedPaths(left as ConfigObject, right as ConfigObject, dotted));
    } else if (JSON.stringify(left) !== JSON.stringify(right)) {
      paths.push(dotted);
    }
  });
  return paths;
}

export const SECTION_TAGS = ["[Intro]", "[Verse]", "[Pre-Chorus]", "[Chorus]", "[Bridge]", "[Outro]"];

export const STYLE_EXAMPLES = [
  "Cinematic Bengali folk-pop, warm male vocal, acoustic guitar, bamboo flute, organic drums, melancholic but hopeful, 92 BPM",
  "English, warm piano pop, expressive female voice, rounded bass and light drums, unhurried phrasing, 88 BPM",
  "Lo-fi hip hop, dusty Rhodes, vinyl crackle, brushed drums, no vocals, 74 BPM",
  "Mandarin ballad, intimate female vocal, nylon guitar, soft strings, 68 BPM",
];
