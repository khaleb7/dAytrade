/**
 * In-source Node shims for tsc on Windows.
 * Loaded via tsconfig include of all files under src.
 * Do not rely on npm @types/node hoist.
 */
declare module "node:fs" {
  const fs: {
    existsSync(path: string): boolean;
    readFileSync(path: string, encoding: BufferEncoding): string;
    readFileSync(path: string, options: { encoding: BufferEncoding; flag?: string }): string;
    readFileSync(path: string, options?: { flag?: string }): Buffer;
    writeFileSync(
      path: string,
      data: string | Uint8Array,
      options?: BufferEncoding | { encoding?: BufferEncoding; flag?: string; mode?: number },
    ): void;
    mkdirSync(path: string, options?: { recursive?: boolean; mode?: number }): string | undefined;
    copyFileSync(src: string, dest: string): void;
    readdirSync(path: string): string[];
    statSync(path: string): { isFile(): boolean; isDirectory(): boolean };
  };
  export = fs;
}

declare module "node:path" {
  const path: {
    join(...paths: string[]): string;
    resolve(...paths: string[]): string;
    dirname(p: string): string;
    basename(p: string, ext?: string): string;
    relative(from: string, to: string): string;
    sep: string;
  };
  export = path;
}

declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
  export function pathToFileURL(path: string): URL;
}

declare module "node:child_process" {
  export interface SpawnOptions {
    cwd?: string;
    env?: Record<string, string | undefined>;
    stdio?: unknown;
  }
  export interface ChildProcess {
    stdout: { on(event: string, cb: (chunk: Buffer | string) => void): void };
    stderr: { on(event: string, cb: (chunk: Buffer | string) => void): void };
    on(event: "close", cb: (code: number | null) => void): void;
  }
  export function spawn(
    command: string,
    args?: readonly string[],
    options?: SpawnOptions,
  ): ChildProcess;
}

declare module "@cursor/sdk" {
  export const Agent: {
    create(options: unknown): Promise<{
      agentId: string;
      send(message: string): Promise<{
        wait?: () => Promise<unknown>;
        stream?: () => AsyncIterable<unknown>;
      }>;
      close?: () => void | Promise<void>;
    }>;
  };
}

type BufferEncoding =
  | "ascii"
  | "utf8"
  | "utf-8"
  | "utf16le"
  | "ucs2"
  | "ucs-2"
  | "base64"
  | "base64url"
  | "latin1"
  | "binary"
  | "hex";

interface Buffer extends Uint8Array {
  toString(encoding?: BufferEncoding): string;
}

declare const Buffer: {
  from(data: string | Uint8Array, encoding?: string): Buffer;
  isBuffer(obj: unknown): boolean;
};

declare const process: {
  env: Record<string, string | undefined>;
  argv: string[];
  cwd(): string;
  exit(code?: number): never;
  stdout: { write(s: string): boolean | void };
  stderr: { write(s: string): boolean | void };
};

declare const console: {
  log(...args: unknown[]): void;
  error(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  info(...args: unknown[]): void;
};

declare function setTimeout(
  handler: (...args: unknown[]) => void,
  timeout?: number,
  ...args: unknown[]
): unknown;
declare function clearTimeout(handle: unknown): void;
declare function setInterval(
  handler: (...args: unknown[]) => void,
  timeout?: number,
  ...args: unknown[]
): unknown;
declare function clearInterval(handle: unknown): void;

declare function fetch(
  input: string | URL,
  init?: {
    method?: string;
    headers?: Record<string, string>;
    body?: string;
  },
): Promise<{
  ok: boolean;
  status: number;
  text(): Promise<string>;
  json(): Promise<unknown>;
}>;

interface ImportMeta {
  url: string;
}
