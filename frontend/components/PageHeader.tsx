export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="mb-8">
      <h1 className="text-3xl font-extrabold tracking-tight sm:text-4xl">{title}</h1>
      {description ? <p className="mt-2 max-w-[60ch] text-muted">{description}</p> : null}
    </header>
  );
}
