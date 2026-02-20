import express from "express";
import { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, makeCacheableSignalKeyStore } from "@whiskeysockets/baileys";
import pino from "pino";
import qrcode from "qrcode";
import fs from "fs";
import path from "path";

const app = express();
app.use(express.json());

const AUTH_DIR = "/tmp/auth";
const WEBHOOK_URL = process.env.WEBHOOK_URL || "http://host.docker.internal:8000/webhooks/whatsapp";
const PORT = process.env.PORT || 8081;

if (!fs.existsSync(AUTH_DIR)) {
    fs.mkdirSync(AUTH_DIR, { recursive: true });
}

let sock = null;
let currentQr = null;
let currentPairingCode = null;
let connectionState = "close";
let isConnecting = false;  // Prevent overlapping connection attempts
let reconnectTimer = null;

const logger = pino({ level: 'info' });

// Prevent container crashes from Baileys internal Boom errors
process.on('uncaughtException', (err) => {
    logger.error(`Uncaught Exception: ${err.message}`);
});
process.on('unhandledRejection', (reason, promise) => {
    logger.error(`Unhandled Rejection: ${reason}`);
});

function forceClearAuth() {
    try {
        if (fs.existsSync(AUTH_DIR)) {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        }
    } catch (e) {
        // Ignore
    }
}

async function connectToWhatsApp() {
    // Prevent overlapping connection attempts
    if (isConnecting) {
        logger.info('Connection attempt already in progress, skipping');
        return;
    }
    isConnecting = true;

    // Clear any pending reconnect timer
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }

    // Close existing socket cleanly
    if (sock) {
        try {
            sock.ev.removeAllListeners();
            sock.ws?.close();
        } catch (e) { }
        sock = null;
    }

    try {
        const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
        const { version, isLatest } = await fetchLatestBaileysVersion();
        logger.info(`using WA v${version.join('.')}, isLatest: ${isLatest}`);

        sock = makeWASocket({
            version,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false,
            auth: {
                creds: state.creds,
                keys: makeCacheableSignalKeyStore(state.keys, logger),
            },
            generateHighQualityLinkPreview: true,
            getMessage: async () => {
                return { conversation: 'hello' }
            },
            defaultQueryTimeoutMs: 60000,
        });

        sock.ev.on('creds.update', saveCreds);

        sock.ev.on('connection.update', (update) => {
            try {
                const { connection, lastDisconnect, qr } = update;

                if (qr) {
                    currentQr = qr;
                    connectionState = "qr";
                    logger.info('QR code received');
                }

                if (connection === 'close') {
                    currentQr = null;
                    currentPairingCode = null;
                    connectionState = "close";
                    isConnecting = false;  // Allow new connection attempts

                    const statusCode = (lastDisconnect?.error)?.output?.statusCode;
                    const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
                    logger.info(`connection closed (status: ${statusCode}), reconnecting: ${shouldReconnect}`);

                    if (shouldReconnect) {
                        // Reconnect after delay, prevent overlapping
                        reconnectTimer = setTimeout(() => connectToWhatsApp(), 5000);
                    } else {
                        sock = null;
                        forceClearAuth();
                    }
                } else if (connection === 'open') {
                    logger.info('opened connection');
                    currentQr = null;
                    currentPairingCode = null;
                    connectionState = "open";
                    isConnecting = false;  // Connection established
                }
            } catch (err) {
                logger.error(`Connection update error: ${err.message}`);
                isConnecting = false;
            }
        });

        sock.ev.on('messages.upsert', async m => {
            logger.info(`Received messages.upsert: ${JSON.stringify(m).substring(0, 500)}`);
            try {
                const resp = await fetch(WEBHOOK_URL, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        event: "messages.upsert",
                        data: m
                    })
                });
                logger.info(`Webhook response: ${resp.status}`);
            } catch (e) {
                logger.error(`Webhook failed: ${e.message}`);
            }
        });
    } catch (e) {
        logger.error(`Failed to initialize socket: ${e.message}`);
        isConnecting = false;
        // Retry after delay
        reconnectTimer = setTimeout(() => connectToWhatsApp(), 5000);
    }
}

// API endpoints
app.get("/status", (req, res) => {
    res.json({ state: connectionState });
});

app.post("/start", async (req, res) => {
    if (connectionState === "open") {
        return res.json({ state: "open" });
    }
    connectToWhatsApp();
    res.json({ state: "connecting" });
});

app.get("/qr", async (req, res) => {
    if (connectionState === "open") {
        return res.status(400).json({ error: "Already connected" });
    }
    if (!currentQr) {
        if (!sock && !isConnecting) connectToWhatsApp();
        return res.status(404).json({ error: "QR not ready yet" });
    }
    try {
        const base64 = await qrcode.toDataURL(currentQr);
        res.json({ qrcode: base64.split(",")[1] });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.post("/pair", async (req, res) => {
    if (connectionState === "open") {
        return res.status(400).json({ error: "Already connected" });
    }
    const { number } = req.body;
    if (!number) return res.status(400).json({ error: "Number required" });

    try {
        if (!sock && !isConnecting) connectToWhatsApp();

        setTimeout(async () => {
            try {
                const code = await sock.requestPairingCode(number);
                currentPairingCode = code;
            } catch (e) {
                logger.error(`Pairing error: ${e.message}`);
            }
        }, 2000);

        res.json({ code: "requested..." });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

app.get("/pair", (req, res) => {
    res.json({ code: currentPairingCode });
});

app.post("/disconnect", (req, res) => {
    if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
    }
    if (sock) {
        try {
            sock.ev.removeAllListeners();
            sock.logout();
        } catch (e) { }
        sock = null;
    }
    isConnecting = false;
    connectionState = "close";
    currentQr = null;
    currentPairingCode = null;
    forceClearAuth();
    res.json({ ok: true });
});

app.post("/sendText", async (req, res) => {
    if (connectionState !== "open") {
        return res.status(400).json({ error: "Not connected" });
    }
    const { number, text } = req.body;
    try {
        const jid = number.includes("@s.whatsapp.net") ? number : `${number}@s.whatsapp.net`;
        await sock.sendMessage(jid, { text });
        res.json({ ok: true });
    } catch (e) {
        res.status(500).json({ error: e.message });
    }
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
    logger.info(`Baileys Microservice running on port ${PORT}`);
    if (fs.existsSync(path.join(AUTH_DIR, 'creds.json'))) {
        logger.info("Found existing creds, auto-connecting...");
        connectToWhatsApp();
    }
});
