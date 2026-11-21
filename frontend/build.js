// Static build: copies index.html and writes config.js with the backend URL (env API_URL).
const fs = require("fs");
fs.mkdirSync("dist", { recursive: true });
fs.copyFileSync("index.html", "dist/index.html");
fs.writeFileSync("dist/config.js", `window.API_URL=${JSON.stringify(process.env.API_URL || "https://ai-chat-litellm.onrender.com")};\n`);
console.log("built dist/ with API_URL =", process.env.API_URL || "https://ai-chat-litellm.onrender.com");
