// The helper side. Helpers are young volunteers on phones and laptops, so this
// is the design system's native density — 16px type, compact controls,
// conventional patterns — not the senior screens' large-print rules.
export default function HelperLayout({ children }: LayoutProps<"/m">) {
  return (
    <div className="min-h-dvh bg-bg text-[0.8rem] leading-normal">
      <div className="mx-auto flex min-h-dvh max-w-6xl flex-col px-4 py-5 sm:px-8">{children}</div>
    </div>
  );
}
