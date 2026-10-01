import { ModelDownloads } from "@/components/settings/model-downloads";

export default async function DownloadModelPage({ searchParams }: {
  searchParams: Promise<{ repo?: string; revision?: string; file?: string }>;
}) {
  const source = await searchParams;
  return <div className="space-y-5">
    <header><h1 className="text-xl font-semibold tracking-tight">Download Model</h1>
      <p className="mt-1 max-w-2xl text-sm text-[var(--color-ink-muted)]">Inspect a Hugging Face repository, choose its content and review storage and hardware estimates before installing.</p></header>
    <ModelDownloads key={JSON.stringify(source)} initialRepo={source.repo} initialRevision={source.revision} initialFile={source.file} />
  </div>;
}
