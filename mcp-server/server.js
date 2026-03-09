import express from "express";
import https from "https";
import fs from "fs";
import sqlite3 from "sqlite3";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { z } from "zod";

const app = express();
const db = new sqlite3.Database("./dummy.db");

// Initialize the MCP Server
const server = new McpServer({
  name: "Secure-SQLite-MCP",
  version: "1.0.0",
});

// Register a real tool that does actual work (variable latency and payload size)
server.tool(
  "query_logs",
  { limit: z.number().max(5000).describe("Number of rows to fetch") },
  async ({ limit }) => {
    return new Promise((resolve, reject) => {
      // Intentional artificial delay to mimic complex query/LLM thinking
      const latencyOptions = [
        () => Math.random() * 100 + 50, // fast
        () => Math.random() * 500 + 200, // medium
        () => Math.random() * 3000 + 1000, // slow
      ];

      const latency =
        latencyOptions[Math.floor(Math.random() * latencyOptions.length)]();

      setTimeout(() => {
        db.all(
          `SELECT * FROM logs ORDER BY RANDOM() LIMIT ?`,
          [limit],
          (err, rows) => {
            if (err) return reject(err);
            resolve({
              content: [{ type: "text", text: JSON.stringify(rows, null, 2) }],
            });
          },
        );
      }, latency);
    });
  },
);

// Global transport reference
let transport;

// Set up the SSE endpoint
app.get("/sse", async (req, res) => {
  console.log("New SSE connection established");
  transport = new SSEServerTransport("/message", res);
  await server.connect(transport);
});

// Set up the message receiving endpoint
app.post("/message", async (req, res) => {
  if (transport) {
    await transport.handlePostMessage(req, res);
  } else {
    res.status(503).send("SSE connection not established");
  }
});

// Boot the HTTPS server
const httpsOptions = {
  key: fs.readFileSync("key.pem"),
  cert: fs.readFileSync("cert.pem"),
};

https.createServer(httpsOptions, app).listen(8443, () => {
  console.log("Secure MCP Server running on https://localhost:8443/sse");
});
