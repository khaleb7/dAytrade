import { CursorAgentError, Agent } from "@cursor/sdk";
import type { Proposal } from "./types.js";
import { absorbStreamEvent, recoverProposal, type StreamCapture } from "./proposal.js";

type SdkRun = {
  stream?: () => AsyncIterable<unknown>;
  wait?: () => Promise<unknown>;
  supports?: (op: string) => boolean;
};

export async function runAgent(opts: {
  workDir: string;
  prompt: string;
  asOf: string;
  modelId: string;
  timeoutMs: number;
}): Promise<Proposal> {
  const apiKey = process.env.CURSOR_API_KEY || "";
  if (!apiKey) throw new Error("Missing CURSOR_API_KEY");
  const agent = await Agent.create({
    apiKey,
    model: { id: opts.modelId },
    local: { cwd: opts.workDir },
  });
  try {
    const run = (await agent.send(opts.prompt)) as SdkRun;
    const capture: StreamCapture = { text: "", writes: [] };
    const work = async () => {
      if (typeof run.stream === "function") {
        for await (const ev of run.stream()) absorbStreamEvent(ev, capture);
      }
      if (typeof run.wait === "function") {
        const result = await run.wait();
        const rec = result && typeof result === "object" ? (result as Record<string, unknown>) : null;
        if (rec && rec.status === "error") {
          throw new Error(`agent run failed: ${String(rec.id || "")}`);
        }
        if (rec && typeof rec.result === "string") capture.text += rec.result;
      }
    };
    await Promise.race([
      work(),
      new Promise((_, reject) =>
        setTimeout(() => reject(new Error("fanout timeout")), opts.timeoutMs),
      ),
    ]);
    const proposal = recoverProposal(opts.workDir, opts.asOf, capture);
    if (!proposal) throw new Error("A1 proposal missing");
    return proposal;
  } catch (err) {
    if (err instanceof CursorAgentError) {
      throw new Error(`Cursor agent did not start: ${err.message}`);
    }
    throw err;
  } finally {
    const dispose = (agent as { [Symbol.asyncDispose]?: () => Promise<void> })[Symbol.asyncDispose];
    if (dispose) await dispose.call(agent);
  }
}
