"use client";

import { useEffect, useState } from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RetentionForm } from "@/components/retention/retention-form";

import { SettingsForm } from "./settings-form";

// Tab ids double as URL hash anchors so /settings#retention deep-links to the
// retention pane (e.g. from the dashboard widget). useEffect runs after mount
// to avoid SSR/CSR mismatch on the default tab.
const VALID_TABS = ["general", "retention"] as const;
type TabId = (typeof VALID_TABS)[number];

function hashToTab(hash: string): TabId | null {
  const id = hash.replace(/^#/, "");
  return (VALID_TABS as readonly string[]).includes(id) ? (id as TabId) : null;
}

export function SettingsTabs() {
  const [tab, setTab] = useState<TabId>("general");

  useEffect(() => {
    const sync = () => {
      const next = hashToTab(window.location.hash);
      if (next) setTab(next);
    };
    sync();
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  const handleChange = (value: string) => {
    const next = (VALID_TABS as readonly string[]).includes(value) ? (value as TabId) : "general";
    setTab(next);
    if (typeof window !== "undefined") {
      // Update the hash without scroll-jumping or pushing a new history entry.
      const url = `${window.location.pathname}${window.location.search}#${next}`;
      window.history.replaceState(null, "", url);
    }
  };

  return (
    <Tabs value={tab} onValueChange={handleChange} className="space-y-4">
      <TabsList>
        <TabsTrigger value="general">General</TabsTrigger>
        <TabsTrigger value="retention">Retention</TabsTrigger>
      </TabsList>
      <TabsContent value="general">
        <SettingsForm />
      </TabsContent>
      <TabsContent value="retention">
        <RetentionForm />
      </TabsContent>
    </Tabs>
  );
}
