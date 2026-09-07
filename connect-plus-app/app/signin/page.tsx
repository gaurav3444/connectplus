import { cookies } from "next/headers";

// Placeholder so the tiles don't 404. Screen 1 is not in scope yet.
export default async function SignIn() {
  const lang = (await cookies()).get("lang")?.value ?? "(not set)";
  return (
    <div className="flex min-h-dvh justify-center bg-bg">
      <main className="w-full max-w-3xl px-6 py-10 sm:px-10">
        <h1 className="text-heading font-medium">Sign in — coming soon</h1>
        <p className="mt-4 text-muted">Language chosen: {lang}</p>
      </main>
    </div>
  );
}
