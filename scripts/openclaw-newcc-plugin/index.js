import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import path from "node:path";

const pexec = promisify(execFile);

// The relay admin scripts (bind-claude-code.py, claude-code-admin.py) live in
// this plugin's parent directory (the relay `scripts/` dir). Self-locate so the
// plugin is portable; override with CC_RELAY_SCRIPTS if they live elsewhere.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPTS = process.env.CC_RELAY_SCRIPTS || path.resolve(__dirname, "..");

// Run one of the relay's deterministic admin scripts and return its text output.
// These scripts patch openclaw.json bindings and (with --restart) schedule a
// DETACHED + delayed gateway restart, so this call returns promptly with the
// reply text before the gateway actually reloads.
async function runScript(file, args, logger) {
  try {
    const { stdout } = await pexec("python3", [`${SCRIPTS}/${file}`, ...args], {
      timeout: 60000,
      cwd: SCRIPTS,
      maxBuffer: 1 << 20,
    });
    return stdout.trim() || "(done)";
  } catch (e) {
    const stderr = (e.stderr || "").toString().trim();
    const stdout = (e.stdout || "").toString().trim();
    logger?.error?.(`cc-relay: ${file} failed: ${e.message}`);
    return [stdout, stderr].filter(Boolean).join("\n") || `Error running ${file}: ${e.message}`;
  }
}

// Build the Telegram peer id the bind scripts expect: "<chatId>" or
// "<chatId>:topic:<threadId>". The chat/group id is a long (usually negative)
// number embedded in a prefixed conversation field, e.g.
//   to=telegram:-1003550185469   from=telegram:group:-1003550185469:topic:816
// so we extract the first such number from `to` (cleanest), then `from`. The
// senderId is the human and must never be used as the chat id.
function derivePeer(ctx) {
  const sender = String(ctx.senderId ?? "");
  let chatId = null;
  for (const field of [ctx.to, ctx.from, ctx.channelId]) {
    if (field == null) continue;
    const m = String(field).match(/-?\d{5,}/);
    if (m && m[0] !== sender) {
      chatId = m[0];
      break;
    }
  }
  if (!chatId) return null;
  const topic = ctx.messageThreadId;
  return topic != null && String(topic) !== "" ? `${chatId}:topic:${topic}` : chatId;
}

function logCtx(api, ctx, label) {
  api.logger?.info?.(
    `cc-relay /${label}: channel=${ctx.channel} senderId=${ctx.senderId} ` +
      `from=${ctx.from} to=${ctx.to} channelId=${ctx.channelId} accountId=${ctx.accountId} ` +
      `thread=${ctx.messageThreadId} parent=${ctx.threadParentId} ` +
      `peer=${derivePeer(ctx)} args=${JSON.stringify(ctx.args)}`
  );
}

export default definePluginEntry({
  id: "cc-relay-commands",
  name: "Claude Code Relay Commands",
  description:
    "Pre-agent /newcc, /unbind, /ccstatus slash commands that bind Telegram " +
    "chats/topics to per-folder Claude Code TUI relays without invoking an LLM.",
  register(api) {
    api.registerCommand({
      name: "newcc",
      description: "Bind this chat/topic to a Claude Code relay folder by code.",
      acceptsArgs: true,
      channels: ["telegram"],
      handler: async (ctx) => {
        logCtx(api, ctx, "newcc");
        const code = (ctx.args ?? "").trim().split(/\s+/)[0] ?? "";
        if (!/^\d{4,8}$/.test(code)) return { text: "Usage: /newcc <code>" };
        const peer = derivePeer(ctx);
        if (!peer) return { text: "Could not determine this chat's id (see gateway log: cc-relay)." };
        return { text: await runScript("bind-claude-code.py", [`--peer=${peer}`, `--code=${code}`, "--restart"], api.logger) };
      },
    });

    api.registerCommand({
      name: "unbind",
      description: "Unbind this chat/topic from its Claude Code relay.",
      acceptsArgs: false,
      channels: ["telegram"],
      handler: async (ctx) => {
        logCtx(api, ctx, "unbind");
        const peer = derivePeer(ctx);
        if (!peer) return { text: "Could not determine this chat's id (see gateway log: cc-relay)." };
        return { text: await runScript("claude-code-admin.py", ["unbind", `--peer=${peer}`, "--restart"], api.logger) };
      },
    });

    api.registerCommand({
      name: "ccstatus",
      description: "Show current Claude Code relay bindings.",
      acceptsArgs: false,
      channels: ["telegram"],
      handler: async (ctx) => {
        logCtx(api, ctx, "ccstatus");
        const out = await runScript("claude-code-admin.py", ["status"], api.logger);
        return { text: `${out}\n\n(this peer: ${derivePeer(ctx) ?? "unknown"})` };
      },
    });
  },
});
