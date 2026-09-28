/**
 * Minimal Node ambient types for DayTrade services builds.
 * Fallback when npm does not hoist @types/node (common on Windows workspaces).
 * Prefer real @types/node via typeRoots order when it is installed.
 */
declare module "node:fs" {
  export function existsSync(path: string): boolean;
  export function readFileSync(path: string, encoding: BufferEncoding): string;
  export function readFileSync(
    path: string,
    options: { encoding: BufferEncoding; flag?: string },
  ): string;
  export function readFileSync(path: string, options?: { flag?: string }): Buffer;
  export function writeFileSync(
    path: string,
    data: string | Uint8Array,
    options?: BufferEncoding | { encoding?: BufferEncoding; flag?: string; mode?: number },
  ): void;
  export function mkdirSync(
    path: string,
    options?: { recursive?: boolean; mode?: number },
  ): string | undefined;
  export function copyFileSync(src: string, dest: string): void;
  export function readdirSync(path: string): string[];
  export function statSync(path: string): { isFile(): boolean; isDirectory(): boolean };
}

declare module "node:path" {
  export function join(...paths: string[]): string;
  export function resolve(...paths: string[]): string;
  export function dirname(p: string): string;
  export function basename(p: string, ext?: string): string;
  export function relative(from: string, to: string): string;
  export const sep: string;
}

declare module "node:url" {
  export function fileURLToPath(url: string | URL): string;
  export function pathToFileURL(path: string): URL;
}

declare module "node:child_process" {
  export interface SpawnOptions {
    cwd?: string;
    env?: NodeJS.ProcessEnv;
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

declare namespace NodeJS {
  interface ProcessEnv {
    [key: string]: string | undefined;
  }
  interface Process {
    env: ProcessEnv;
    argv: string[];
    cwd(): string;
    exit(code?: number): never;
    stdout: { write(s: string): boolean | void };
    stderr: { write(s: string): boolean | void };
  }
}

declare var process: NodeJS.Process;
declare var console: {
  log(...args: unknown[]): void;
  error(...args: unknown[]): void;
  warn(...args: unknown[]): void;
  info(...args: unknown[]): void;
};
declare var setTimeout: (
  handler: (...args: unknown[]) => void,
  timeout?: number,
  ...args: unknown[]
) => unknown;
declare var clearTimeout: (handle: unknown) => void;
declare var setInterval: (
  handler: (...args: unknown[]) => void,
  timeout?: number,
  ...args: unknown[]
) => unknown;
declare var clearInterval: (handle: unknown) => void;
declare var Buffer: {
  from(data: string | Uint8Array, encoding?: string): Buffer;
  isBuffer(obj: unknown): boolean;
};
interface Buffer extends Uint8Array {
  toString(encoding?: BufferEncoding): string;
}
declare type BufferEncoding =
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

interface ImportMeta {
  url: string;
}

interface SymbolConstructor {
  readonly asyncDispose: unique symbol;
}

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

declare module "@cursor/sdk" {
  export const Agent: {
    create(options: unknown): Promise<{
      agentId: string;
      send(message: string): Promise<{
        wait?: () => Promise<unknown>;
        stream?: () => AsyncIterable<unknown>;
      }>;
      close?: () => void | Promise<void>;
      [Symbol.asyncDispose]?: () => void | Promise<void>;
    }>;
  };
}
