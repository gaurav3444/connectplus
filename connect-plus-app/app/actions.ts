"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { signOut } from "./session";

const YEAR = { maxAge: 60 * 60 * 24 * 365, path: "/", sameSite: "lax" } as const;

// The A+ control. One cookie, read by the root layout, scales every screen —
// the app is sized in rem so nothing has to know about it.
export async function toggleTextSize(formData: FormData) {
  const jar = await cookies();
  const big = jar.get("text-size")?.value === "lg";
  jar.set("text-size", big ? "md" : "lg", YEAR);
  // back: the screen the control was pressed on, so it stays put.
  redirect(String(formData.get("back") ?? "/"));
}

// Sign out. Free-standing so any screen's header can post to it.
export async function endSession() {
  await signOut();
}
