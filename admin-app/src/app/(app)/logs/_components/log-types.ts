export type LogLevel = "DEBUG" | "INFO" | "WARN" | "ERROR";

export interface LogLine {
  ts: string;
  container: string;
  stream: "stdout" | "stderr";
  level?: LogLevel;
  line: string;
  id: number; // monotonic, assigned client-side
}
