"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { signOut } from "./session";

const YEAR = { maxAge: 60 * 60 * 24 * 365, path: "/", sameSite: "lax" } as const;

// The A+ control. One cookie, read by the root layout, scales every screen —
// the app is sized in rem so nothing has to know about it.
export async function toggleTextSize(formData: FormData) {
  const jar = await cookies();
  // any step up goes back to normal; normal goes up one
  const up = ["lg", "xl"].includes(jar.get("text-size")?.value ?? "");
  jar.set("text-size", up ? "md" : "lg", YEAR);
  // back: the screen the control was pressed on, so it stays put.
  redirect(String(formData.get("back") ?? "/"));
}

// Settings: the size of the writing, picked directly.
export async function setTextSize(formData: FormData) {
  const size = String(formData.get("size"));
  (await cookies()).set("text-size", ["md", "lg", "xl"].includes(size) ? size : "md", YEAR);
  redirect("/settings");
}

// Settings: black background, white writing.
export async function toggleContrast() {
  const jar = await cookies();
  jar.set("contrast", jar.get("contrast")?.value === "high" ? "normal" : "high", YEAR);
  redirect("/settings");
}

// Settings: dark writing on a light background.
export async function toggleTheme() {
  const jar = await cookies();
  jar.set("theme", jar.get("theme")?.value === "light" ? "dark" : "light", YEAR);
  redirect("/settings");
}

// Sign out. Free-standing so any screen's header can post to it.
export async function endSession() {
  await signOut();
}
