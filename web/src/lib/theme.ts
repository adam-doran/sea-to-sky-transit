// Light, dark, or follow the device. The choice is kept in this browser only.

export type ThemePreference = "system" | "light" | "dark";
export type Theme = "light" | "dark";

export const THEME_KEY = "layover-theme";
export const THEME_PREFERENCES: readonly ThemePreference[] = ["system", "light", "dark"];

export function resolveTheme(pref: ThemePreference, systemDark: boolean): Theme {
  if (pref === "system") return systemDark ? "dark" : "light";
  return pref;
}

export function parsePreference(value: string | null | undefined): ThemePreference {
  return value === "light" || value === "dark" ? value : "system";
}

/** localStorage can be unavailable (private windows, blocked storage): never let that break the app. */
export function loadPreference(storage: Pick<Storage, "getItem"> | undefined): ThemePreference {
  try {
    return parsePreference(storage?.getItem(THEME_KEY));
  } catch {
    return "system";
  }
}

export function savePreference(storage: Pick<Storage, "setItem" | "removeItem"> | undefined, pref: ThemePreference): void {
  try {
    if (pref === "system") storage?.removeItem(THEME_KEY);
    else storage?.setItem(THEME_KEY, pref);
  } catch {
    // Not remembered this time; the switch still works for this visit
  }
}
