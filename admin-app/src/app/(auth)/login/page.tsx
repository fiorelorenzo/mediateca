import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { login } from "./actions";

export default async function LoginPage(props: {
  searchParams: Promise<{ error?: string }>;
}) {
  const { error } = await props.searchParams;
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4">
      <form action={login} className="w-full max-w-sm space-y-4 rounded-lg border bg-card p-8 shadow-sm">
        <h1 className="text-2xl font-semibold">Mediateca</h1>
        <p className="text-sm text-muted-foreground">Admin sign-in</p>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input id="password" name="password" type="password" autoFocus required />
        </div>
        {error === "invalid" && <p className="text-sm text-destructive">Invalid password.</p>}
        {error === "missing" && <p className="text-sm text-destructive">Enter a password.</p>}
        <Button type="submit" className="w-full">Sign in</Button>
      </form>
    </main>
  );
}
