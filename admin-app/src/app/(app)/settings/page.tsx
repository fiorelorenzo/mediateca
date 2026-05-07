import type { Metadata } from "next";
import { SettingsForm } from "./_components/settings-form";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Runtime configuration. Stored in the orchestrator DB.
        </p>
      </div>
      <SettingsForm />
    </div>
  );
}
