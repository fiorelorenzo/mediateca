import { RequestsList } from "./_components/requests-list";

export default function RequestsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Requests</h1>
        <p className="text-muted-foreground">
          Pending Seerr requests. Approving here is the same as in Seerr&apos;s UI.
        </p>
      </div>
      <RequestsList />
    </div>
  );
}
