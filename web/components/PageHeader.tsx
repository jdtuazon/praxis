import { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-8">
      <div className="label text-iris">{eyebrow}</div>
      <h1 className="mt-2 text-balance text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
      {children && <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-dim">{children}</p>}
    </header>
  );
}
