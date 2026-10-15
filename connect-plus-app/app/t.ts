import { cookies } from "next/headers";
import { dict } from "./i18n";

// The language picked on screen 0, read on the server so every screen renders
// in it straight away — no flash of English, works with JavaScript off.
export async function getLang() {
  return (await cookies()).get("lang")?.value ?? "en";
}

export async function getT() {
  return dict(await getLang());
}
