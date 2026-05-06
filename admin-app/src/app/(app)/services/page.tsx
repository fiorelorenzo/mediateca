import { ExternalLink } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { orchestrator } from "@/lib/api/orchestrator";

export default async function ServicesPage() {
  const services = await orchestrator.services().catch(() => []);
  const domain = process.env.PUBLIC_DOMAIN ?? "localhost";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Services</h1>
        <p className="text-muted-foreground">Native UIs for each component of the stack.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {services.map((s) => (
          <a key={s.key} href={`https://${s.subdomain}.${domain}`} target="_blank" rel="noopener noreferrer"
             className="group">
            <Card className="transition-colors group-hover:border-primary">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-base">{s.name}</CardTitle>
                <ExternalLink className="size-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-sm font-mono text-muted-foreground">{s.subdomain}.{domain}</div>
              </CardContent>
            </Card>
          </a>
        ))}
      </div>
    </div>
  );
}
